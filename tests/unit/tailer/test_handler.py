import logging
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock

import pytest
from watchdog.events import (
    FileCreatedEvent,
    DirCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    DirModifiedEvent,
    DirDeletedEvent,
    DirMovedEvent,
)

from datamover.queues.queue_functions import QueuePutError
from datamover.tailer.data_class import (
    TailerQueueEvent,
    CreatedEvent,
    ModifiedEvent,
    DeletedEvent,
    MovedEvent,
)
from datamover.tailer.handler import MappingEventHandler
from tests.test_utils.logging_helpers import (
    find_log_record,
)

LOGGER = "datamover.tailer.handler"
EXT = "txt"  # Default extension for tests
TIMEOUT = 0.1


# -- Helpers --
def make_event(event_cls, path: Path, bytes_path: bool = False):
    """Helper to create watchdog event instances with string or byte paths."""
    raw_path = bytes(str(path), "utf-8") if bytes_path else str(path)
    return event_cls(raw_path)


def make_moved_event(src_path: Path, dest_path: Path, bytes_paths: bool = False):
    """Helper to create watchdog FileMovedEvent or DirMovedEvent instances."""
    # Note: Watchdog event classes handle str or bytes paths.
    raw_src_path = bytes(str(src_path), "utf-8") if bytes_paths else str(src_path)
    raw_dest_path = bytes(str(dest_path), "utf-8") if bytes_paths else str(dest_path)
    # This helper was for FileMovedEvent, but DirMovedEvent has the same signature.
    # If it needs to be specific, the caller can pass FileMovedEvent or DirMovedEvent to event_cls in make_event
    return FileMovedEvent(raw_src_path, raw_dest_path)


# -- Fixtures --
@pytest.fixture
def mock_event_queue() -> MagicMock:
    """Provides a MagicMock for the event queue."""
    return MagicMock(spec=Queue)


@pytest.fixture
def handler_factory(
    tmp_path: Path,
    mock_event_queue: MagicMock,
    mock_fs: MagicMock,  # Assuming mock_fs comes from conftest.py
):
    """
    Factory to create and configure MappingEventHandler instances for tests.
    Configures the provided 'mock_fs' with default behaviors.
    """
    # Initial configuration of mock_fs instance for the duration of the factory's use in a test
    mock_fs.resolve = MagicMock(side_effect=lambda p, strict=False: Path(p))
    mock_fs.relative_to = MagicMock(
        side_effect=lambda p, base: Path(p).relative_to(base)
    )
    mock_fs.exists = MagicMock(return_value=True)
    mock_fs.is_dir = MagicMock(return_value=True)

    def _make(
        ext: str = EXT,
        initial_paths: set[Path] | None = None,
        timeout: float | None = TIMEOUT,
        fs_override: MagicMock | None = None,
        watched_dir_override: Path | None = None,
    ) -> tuple[MappingEventHandler, set[str], MagicMock, Path]:
        current_fs = fs_override if fs_override is not None else mock_fs
        # If watched_dir_override is None, use tmp_path directly as the watched dir.
        # If a specific sub-structure is needed by default, it can be created here.
        watched_dir = (
            watched_dir_override if watched_dir_override is not None else tmp_path
        )
        if (
            watched_dir_override is None and not tmp_path.exists()
        ):  # Ensure tmp_path itself exists if used as watched_dir
            tmp_path.mkdir(parents=True, exist_ok=True)

        # Reset and reapply default behaviors if using the shared mock_fs
        # This ensures a clean state for each handler instance created by this factory call.
        if current_fs == mock_fs:
            # Reset specific methods
            for method_name, default_side_effect, default_return_value in [
                ("resolve", lambda p, strict=False: Path(p), None),
                ("relative_to", lambda p, base: Path(p).relative_to(base), None),
                ("exists", None, True),
                ("is_dir", None, True),
            ]:
                mock_attr = getattr(current_fs, method_name)
                mock_attr.reset_mock(
                    return_value=True, side_effect=True
                )  # Clear previous state
                if default_side_effect:
                    mock_attr.side_effect = default_side_effect
                else:
                    mock_attr.return_value = default_return_value

            current_fs.reset_mock()  # Reset the main mock object (e.g., call_count for current_fs itself)

        file_map_str = {str(p) for p in (initial_paths or set())}

        handler = MappingEventHandler(
            file_map=file_map_str,
            event_queue=mock_event_queue,
            watched_directory=watched_dir,
            fs=current_fs,
            file_extension=ext,
            queue_timeout=timeout,
        )
        return handler, file_map_str, mock_event_queue, watched_dir

    return _make


@pytest.fixture
def handler_and_deps(handler_factory, tmp_path: Path):
    """Provides a common handler setup with a 'watched' subdirectory."""
    watched_subdir_name = "watched"  # Standardized name
    watched_path = tmp_path / watched_subdir_name
    watched_path.mkdir(parents=True, exist_ok=True)

    # Pass the specific extension from the global constant
    handler, file_map, queue_mock, effective_watched_dir = handler_factory(
        ext=EXT, watched_dir_override=watched_path
    )
    return handler, file_map, queue_mock, effective_watched_dir


# -- Initialization --
def test_init_and_log(
    tmp_path: Path,
    mock_event_queue: MagicMock,
    mock_fs: MagicMock,
    caplog: pytest.LogCaptureFixture,
):
    """Test handler initialization and its initial log message."""
    caplog.set_level(logging.INFO, logger=LOGGER)
    handler = MappingEventHandler(
        file_map=set(),
        event_queue=mock_event_queue,
        watched_directory=tmp_path,
        fs=mock_fs,
        file_extension=".TEST",
        queue_timeout=0.2,
    )
    assert handler.file_extension == ".test"
    assert handler.watched_directory == tmp_path
    log_record = find_log_record(
        caplog,
        logging.INFO,
        ["MappingEventHandler initialized", str(tmp_path), ".test"],
    )
    assert log_record is not None


# -- _safe_enqueue --
def test_safe_enqueue_success(handler_factory, caplog: pytest.LogCaptureFixture):
    """Test successful event enqueuing and logging."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    handler, _, queue_mock, _ = (
        handler_factory()
    )  # Uses tmp_path as watched_dir by default
    event_to_enqueue = CreatedEvent(path="/path/to/a.txt")

    handler._safe_enqueue(event_to_enqueue)

    queue_mock.put.assert_called_once_with(
        event_to_enqueue, block=True, timeout=handler.queue_timeout
    )
    log_record = find_log_record(
        caplog, logging.DEBUG, ["Enqueued event:", str(event_to_enqueue)]
    )
    assert log_record is not None


@pytest.mark.parametrize(
    "exception_to_raise",
    [QueuePutError("Queue is full"), RuntimeError("Unexpected failure")],
)
def test_safe_enqueue_failure_logs(
    handler_factory,
    caplog: pytest.LogCaptureFixture,
    mocker: MagicMock,
    exception_to_raise: Exception,
):
    """Test failure scenarios during event enqueuing and appropriate logging."""
    log_level_for_error = (
        logging.ERROR
        if isinstance(exception_to_raise, QueuePutError)
        else logging.CRITICAL
    )
    caplog.set_level(min(logging.ERROR, log_level_for_error), logger=LOGGER)

    handler, _, queue_mock, _ = handler_factory()
    event_to_enqueue = CreatedEvent(path="/path/to/a.txt")

    patched_safe_put = mocker.patch(
        "datamover.tailer.handler.safe_put", side_effect=exception_to_raise
    )

    if isinstance(exception_to_raise, QueuePutError):
        handler._safe_enqueue(event_to_enqueue)
        log_record = find_log_record(
            caplog,
            logging.ERROR,
            ["Failed to enqueue event", str(event_to_enqueue), handler.QUEUE_NAME],
        )
        assert log_record is not None
    else:
        with pytest.raises(type(exception_to_raise)):
            handler._safe_enqueue(event_to_enqueue)

    patched_safe_put.assert_called_once_with(
        item=event_to_enqueue,
        output_queue=queue_mock,
        queue_name=handler.QUEUE_NAME,
        timeout=handler.queue_timeout,
    )


# -- _is_path_within_monitored_directory --
@pytest.mark.parametrize(
    "relative_path_str, expected_result, fs_resolve_error",
    [
        ("file.txt", True, None),
        ("sub/file.txt", False, None),
        ("../outside.txt", False, None),
        ("another_file.txt", False, FileNotFoundError("Path does not exist")),
        (
            "problem.path",
            False,
            ValueError("Invalid path components"),
        ),  # Simulating relative_to error
        ("unexpected.err", False, Exception("Unexpected FS error")),
    ],
)
def test_is_path_within_monitored_directory(
    handler_factory,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    relative_path_str: str,
    expected_result: bool,
    fs_resolve_error: Exception | None,
):
    """Test logic for checking if a path is directly within the monitored directory."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    # Use tmp_path directly as the monitored base for this test's flexibility
    handler, _, _, monitored_base_dir = handler_factory(watched_dir_override=tmp_path)

    path_to_check_obj = monitored_base_dir / relative_path_str

    if fs_resolve_error:
        # If the error is ValueError for relative_to, fs.resolve should succeed but relative_to fail.
        # Here, we simplify by having fs.resolve raise the error to test the except blocks.
        handler.fs.resolve = MagicMock(side_effect=fs_resolve_error)
    else:
        # For standard cases, allow fs.resolve to work "normally" (mocked)
        # and fs.relative_to to determine based on path structure.
        handler.fs.resolve.side_effect = lambda p, strict=False: Path(
            p
        ).resolve()  # More realistic resolve
        # Note: Path(p).relative_to(base) naturally raises ValueError if not a subpath.

    result = handler._is_path_within_monitored_directory(str(path_to_check_obj))
    assert result == expected_result

    if fs_resolve_error:
        if isinstance(fs_resolve_error, (FileNotFoundError, OSError)):
            assert (
                find_log_record(
                    caplog,
                    logging.DEBUG,
                    [
                        "Error checking if path",
                        str(path_to_check_obj),
                        "Assuming not within.",
                    ],
                )
                is not None
            )
        elif isinstance(fs_resolve_error, Exception) and not isinstance(
            fs_resolve_error, ValueError
        ):
            assert (
                find_log_record(
                    caplog,
                    logging.ERROR,
                    [
                        "Unexpected error in _is_path_within_monitored_directory",
                        str(path_to_check_obj),
                    ],
                )
                is not None
            )
    # No specific log check for ValueError from relative_to as it's just `return False`.


# -- _should_process_file --
@pytest.mark.parametrize(
    "filename, location_type, expected_processing, expected_log_substring_parts",
    [
        (f"data.{EXT}", "inside", True, None),
        ("data.other_ext", "inside", False, ["does not match extension", f".{EXT}"]),
        (f"another.{EXT}", "outside", False, ["not directly within watched directory"]),
        (
            f"subdir_file.{EXT}",
            "subdir",
            False,
            ["not directly within watched directory"],
        ),
    ],
)
def test_should_process_file(
    handler_factory,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    filename: str,
    location_type: str,
    expected_processing: bool,
    expected_log_substring_parts: list[str] | None,
):
    """Test the logic for deciding whether a file event should be processed."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    # Explicitly create a "root" for watched_dir to make "outside" distinct
    test_root = tmp_path / "spf_root"
    test_root.mkdir()
    watched_dir = test_root / "watched_spf"
    watched_dir.mkdir()

    handler, _, _, _ = handler_factory(watched_dir_override=watched_dir, ext=EXT)

    if location_type == "inside":
        file_path = watched_dir / filename
    elif location_type == "outside":
        file_path = test_root / filename  # Sibling to watched_dir, but outside it
    elif location_type == "subdir":
        subdir = watched_dir / "subfolder"
        subdir.mkdir(exist_ok=True)
        file_path = subdir / filename
    else:
        raise ValueError(f"Unknown location_type: {location_type}")

    result = handler._should_process_file(str(file_path))
    assert result == expected_processing

    if not expected_processing and expected_log_substring_parts:
        # Add file_path to expected log parts as it's usually logged
        full_expected_log_parts = expected_log_substring_parts + [str(file_path)]
        log_record = find_log_record(caplog, logging.DEBUG, full_expected_log_parts)
        assert log_record is not None


# -- Consolidated Event Handling Tests --


@pytest.mark.parametrize("use_byte_path", [False, True])
def test_on_created_valid_file(
    handler_and_deps, caplog: pytest.LogCaptureFixture, use_byte_path: bool
):
    """Test 'on_created' for a relevant file, checking file_map and queue."""
    handler, file_map, queue_mock, watched_dir = handler_and_deps
    caplog.set_level(logging.INFO, logger=LOGGER)

    file_to_create = watched_dir / f"newfile.{EXT}"  # Use EXT from fixture/global
    create_event = make_event(
        FileCreatedEvent, file_to_create, bytes_path=use_byte_path
    )

    handler.on_created(create_event)

    assert str(file_to_create) in file_map
    queue_mock.put.assert_called_once()
    args, kwargs = queue_mock.put.call_args
    assert isinstance(args[0], CreatedEvent)
    assert args[0].path == str(file_to_create)
    assert kwargs["timeout"] == handler.queue_timeout
    assert (
        find_log_record(
            caplog,
            logging.INFO,
            ["Detected relevant file creation", str(file_to_create)],
        )
        is not None
    )


@pytest.mark.parametrize(
    "initially_tracked, expected_event_type, expected_log_level, expected_log_msg_key",
    [
        (False, CreatedEvent, logging.WARNING, "Treating as creation"),
        (True, ModifiedEvent, logging.INFO, "Detected relevant file modification"),
    ],
)
def test_on_modified_file(
    handler_and_deps,
    caplog: pytest.LogCaptureFixture,
    initially_tracked: bool,
    expected_event_type: type[TailerQueueEvent],
    expected_log_level: int,
    expected_log_msg_key: str,
):
    """Test 'on_modified' for files, covering tracked and untracked scenarios."""
    handler, file_map, queue_mock, watched_dir = handler_and_deps
    caplog.set_level(min(logging.INFO, expected_log_level), logger=LOGGER)

    file_to_modify = watched_dir / f"myfile.{EXT}"
    if initially_tracked:
        file_map.add(str(file_to_modify))  # Pre-track the file

    modify_event = make_event(FileModifiedEvent, file_to_modify)
    handler.on_modified(modify_event)

    assert str(file_to_modify) in file_map
    queue_mock.put.assert_called_once()
    args, _ = queue_mock.put.call_args
    assert isinstance(args[0], expected_event_type)
    assert args[0].path == str(file_to_modify)
    assert (
        find_log_record(
            caplog, expected_log_level, [expected_log_msg_key, str(file_to_modify)]
        )
        is not None
    )


@pytest.mark.parametrize("is_tracked_initially", [True, False])
def test_on_deleted_file_inside_watched_dir(
    handler_and_deps, caplog: pytest.LogCaptureFixture, is_tracked_initially: bool
):
    """Test 'on_deleted' for files inside watched_dir (tracked and untracked)."""
    handler, file_map, queue_mock, watched_dir = handler_and_deps
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    file_to_delete = watched_dir / f"delete_me.{EXT}"
    if is_tracked_initially:
        file_map.add(str(file_to_delete))

    delete_event = make_event(FileDeletedEvent, file_to_delete)
    handler.on_deleted(delete_event)

    if is_tracked_initially:
        assert str(file_to_delete) not in file_map
        queue_mock.put.assert_called_once()
        args, _ = queue_mock.put.call_args
        assert isinstance(args[0], DeletedEvent)
        assert args[0].path == str(file_to_delete)
        assert (
            find_log_record(
                caplog,
                logging.INFO,
                ["Detected relevant file deletion", str(file_to_delete)],
            )
            is not None
        )
    else:
        assert str(file_to_delete) not in file_map
        queue_mock.put.assert_not_called()
        assert (
            find_log_record(
                caplog,
                logging.DEBUG,
                [
                    "Ignoring deletion for untracked or irrelevant file",
                    str(file_to_delete),
                ],
            )
            is not None
        )


def test_on_deleted_file_outside_watched_directory(
    handler_factory, caplog: pytest.LogCaptureFixture, tmp_path: Path
):
    """Test 'on_deleted' for a file outside watched directory is ignored."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    base_test_path = tmp_path / "delete_tests_root"
    watched_dir_for_handler = base_test_path / "actual_watched"
    outside_dir = base_test_path / "folder_outside"
    watched_dir_for_handler.mkdir(parents=True, exist_ok=True)
    outside_dir.mkdir(parents=True, exist_ok=True)

    handler, file_map, queue_mock, effective_watched_dir = handler_factory(
        watched_dir_override=watched_dir_for_handler, ext="txt"
    )
    assert effective_watched_dir == watched_dir_for_handler  # Sanity check

    file_to_delete_outside = outside_dir / "some_other_file.txt"
    delete_event = make_event(FileDeletedEvent, file_to_delete_outside)
    handler.on_deleted(delete_event)

    queue_mock.put.assert_not_called()
    assert str(file_to_delete_outside) not in file_map
    expected_logs = [
        "Ignoring deletion for path",
        str(file_to_delete_outside),
        "not directly within watched directory",
        str(effective_watched_dir),
    ]
    assert find_log_record(caplog, logging.DEBUG, expected_logs) is not None


@pytest.mark.parametrize(
    "src_tracked, src_ext_match, dest_in_watched, dest_ext_match, expect_event_queued, expect_dest_in_map_after, log_level, log_substring",
    [
        (
            True,
            True,
            True,
            True,
            True,
            True,
            logging.INFO,
            "Detected relevant file move",
        ),
        (
            True,
            True,
            False,
            True,
            True,
            False,
            logging.INFO,
            "Detected relevant file move",
        ),  # Moved out
        (
            False,
            False,
            True,
            True,
            True,
            True,
            logging.INFO,
            "Detected relevant file move",
        ),
        # Moved in (untracked irrelevant src)
        (
            True,
            True,
            True,
            False,
            True,
            False,
            logging.INFO,
            "Detected relevant file move",
        ),
        # Renamed to irrelevant ext
        (
            False,
            False,
            True,
            True,
            True,
            True,
            logging.INFO,
            "Detected relevant file move",
        ),
        # Renamed from irrelevant to relevant
        (
            False,
            False,
            False,
            False,
            False,
            False,
            logging.DEBUG,
            "Ignoring move event",
        ),  # Fully irrelevant move
        (False, True, False, True, False, False, logging.DEBUG, "Ignoring move event"),
        # Untracked src (but relevant ext) moved outside
        (
            True,
            False,
            True,
            True,
            True,
            True,
            logging.INFO,
            "Detected relevant file move",
        ),
        # Tracked src (wrong ext in map) moved/renamed to relevant
    ],
)
def test_on_moved_file(
    handler_factory,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    src_tracked: bool,
    src_ext_match: bool,
    dest_in_watched: bool,
    dest_ext_match: bool,
    expect_event_queued: bool,
    expect_dest_in_map_after: bool,
    log_level: int,
    log_substring: str,
):
    """Test 'on_moved' for files with various source/destination relevancy."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    test_root = tmp_path / "move_tests_root"
    watched_dir_for_handler = test_root / "watched_area_moves"
    outside_dir = test_root / "outside_area_moves"
    watched_dir_for_handler.mkdir(parents=True, exist_ok=True)
    outside_dir.mkdir(parents=True, exist_ok=True)

    # Use global EXT for handler's expected extension
    handler, file_map, queue_mock, _ = handler_factory(
        watched_dir_override=watched_dir_for_handler, ext=EXT
    )

    src_filename = f"source_file.{EXT if src_ext_match else 'oth'}"
    dest_filename = f"dest_file.{EXT if dest_ext_match else 'oth'}"

    # Source path assumed within watched_dir_for_handler for test simplicity;
    # its "tracked" status and relevance is via params.
    src_path = watched_dir_for_handler / src_filename
    dest_path = (
        (watched_dir_for_handler / dest_filename)
        if dest_in_watched
        else (outside_dir / dest_filename)
    )

    if src_tracked:
        file_map.add(str(src_path))

    move_event = make_moved_event(src_path, dest_path)  # Uses FileMovedEvent by default
    handler.on_moved(move_event)

    if expect_event_queued:
        queue_mock.put.assert_called_once()
        args, _ = queue_mock.put.call_args
        assert isinstance(args[0], MovedEvent)
        assert args[0].src_path == str(src_path) and args[0].dest_path == str(dest_path)
    else:
        queue_mock.put.assert_not_called()

    assert (str(dest_path) in file_map) == expect_dest_in_map_after
    if src_tracked:
        assert str(src_path) not in file_map

    log_record = find_log_record(caplog, log_level, [log_substring])
    assert log_record is not None
    if (
        log_substring == "Detected relevant file move"
    ):  # Check paths in this specific log
        assert (
            str(src_path) in log_record.message and str(dest_path) in log_record.message
        )


def test_on_moved_byte_paths(handler_and_deps, caplog: pytest.LogCaptureFixture):
    """Test on_moved with byte paths."""
    handler, file_map, queue_mock, watched_dir = handler_and_deps
    caplog.set_level(logging.INFO, logger=LOGGER)

    src_file = watched_dir / f"a.{EXT}"
    dest_file = watched_dir / f"b.{EXT}"
    file_map.add(str(src_file))  # Pre-track the source

    event = FileMovedEvent(
        bytes(str(src_file), "utf-8"), bytes(str(dest_file), "utf-8")
    )
    handler.on_moved(event)

    queue_mock.put.assert_called_once()
    args, _ = queue_mock.put.call_args
    assert isinstance(args[0], MovedEvent)
    assert args[0].src_path == str(src_file) and args[0].dest_path == str(dest_file)
    assert (
        find_log_record(
            caplog,
            logging.INFO,
            ["Detected relevant file move", str(src_file), str(dest_file)],
        )
        is not None
    )


@pytest.mark.parametrize(
    "event_name, event_class, handler_method_name, log_message_part",
    [
        ("created", DirCreatedEvent, "on_created", "Ignoring directory creation"),
        (
            "modified",
            DirModifiedEvent,
            "on_modified",
            "Ignoring directory modification",
        ),
        ("deleted", DirDeletedEvent, "on_deleted", "Ignoring directory deletion"),
        ("moved", DirMovedEvent, "on_moved", "Ignoring directory move"),
    ],
)
def test_handler_ignores_directory_events(
    handler_and_deps,
    caplog: pytest.LogCaptureFixture,
    event_name: str,
    event_class: type,
    handler_method_name: str,
    log_message_part: str,
):
    """Test that directory events are ignored by 'on_...' handlers and logged."""
    handler, _, queue_mock, watched_dir = handler_and_deps
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    src_dir_path_str = str(watched_dir / f"some_dir_for_{event_name}_src")

    if event_class == DirMovedEvent:
        dest_dir_path_str = str(watched_dir / f"some_dir_for_{event_name}_dest")
        event_to_fire = event_class(src_dir_path_str, dest_dir_path_str)
        expected_log_substrings = [
            log_message_part,
            src_dir_path_str,
            dest_dir_path_str,
        ]
    else:
        event_to_fire = event_class(src_dir_path_str)
        expected_log_substrings = [log_message_part, src_dir_path_str]

    handler_method = getattr(handler, handler_method_name)
    handler_method(event_to_fire)

    queue_mock.put.assert_not_called()
    log_record = find_log_record(caplog, logging.DEBUG, expected_log_substrings)
    assert log_record is not None, (
        f"Expected log for '{log_message_part}' on dir '{src_dir_path_str}' not found."
    )


@pytest.mark.parametrize(
    "handler_method_name, event_class",
    [
        ("on_created", FileCreatedEvent),
        ("on_modified", FileModifiedEvent),
    ],
)
def test_handler_ignores_file_with_wrong_extension(
    handler_and_deps,
    caplog: pytest.LogCaptureFixture,
    handler_method_name: str,
    event_class: type,
):
    """Test that on_created and on_modified ignore files with the wrong extension."""
    handler, file_map, queue_mock, watched_dir = (
        handler_and_deps  # Default ext is EXT (e.g. ".txt")
    )
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    file_with_wrong_ext = watched_dir / "document.other_ext"

    if handler_method_name == "on_modified":
        file_map.add(str(file_with_wrong_ext))  # Simulate it being erroneously tracked

    event_to_fire = make_event(event_class, file_with_wrong_ext)
    handler_method = getattr(handler, handler_method_name)
    handler_method(event_to_fire)

    queue_mock.put.assert_not_called()

    if handler_method_name == "on_created":
        assert str(file_with_wrong_ext) not in file_map
    elif handler_method_name == "on_modified":  # If pre-added, it should remain
        assert str(file_with_wrong_ext) in file_map

    expected_logs = [
        "does not match extension",
        str(file_with_wrong_ext),
        handler.file_extension,
    ]
    assert find_log_record(caplog, logging.DEBUG, expected_logs) is not None


# -- Smoke sequence test --
def test_event_sequence_smoke(
    handler_factory, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """A smoke test simulating a sequence of file operations."""
    caplog.set_level(logging.INFO, logger=LOGGER)
    watched_dir = tmp_path / "sequence_test_dir"
    watched_dir.mkdir()

    handler, file_map, queue_mock, _ = handler_factory(
        ext="log", watched_dir_override=watched_dir
    )

    file_alpha = watched_dir / "alpha.log"
    file_beta = watched_dir / "beta.log"

    # 1. Create alpha.log
    handler.on_created(make_event(FileCreatedEvent, file_alpha))
    assert str(file_alpha) in file_map
    assert find_log_record(
        caplog, logging.INFO, ["Detected relevant file creation", str(file_alpha)]
    )

    # 2. Modify alpha.log
    handler.on_modified(make_event(FileModifiedEvent, file_alpha))
    assert find_log_record(
        caplog, logging.INFO, ["Detected relevant file modification", str(file_alpha)]
    )

    # 3. Move alpha.log to beta.log
    handler.on_moved(
        make_moved_event(file_alpha, file_beta)
    )  # Using updated make_moved_event
    assert str(file_alpha) not in file_map
    assert str(file_beta) in file_map
    assert find_log_record(
        caplog,
        logging.INFO,
        ["Detected relevant file move", str(file_alpha), str(file_beta)],
    )

    # 4. Delete beta.log
    handler.on_deleted(make_event(FileDeletedEvent, file_beta))
    assert str(file_beta) not in file_map
    assert find_log_record(
        caplog, logging.INFO, ["Detected relevant file deletion", str(file_beta)]
    )

    assert queue_mock.put.call_count == 4
    expected_event_types = [CreatedEvent, ModifiedEvent, MovedEvent, DeletedEvent]
    for i, call_args in enumerate(queue_mock.put.call_args_list):
        queued_item = call_args[0][0]
        assert isinstance(queued_item, expected_event_types[i])
        # Path checks for each event type
        if isinstance(queued_item, (CreatedEvent, ModifiedEvent, DeletedEvent)):
            expected_path = file_alpha if i < 2 else file_beta
            assert queued_item.path == str(
                expected_path
                if not (isinstance(queued_item, MovedEvent) or i == 3)
                else file_beta
            )
        elif isinstance(queued_item, MovedEvent):
            assert queued_item.src_path == str(
                file_alpha
            ) and queued_item.dest_path == str(file_beta)
