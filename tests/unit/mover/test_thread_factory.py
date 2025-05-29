import logging
import threading
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch, call
from typing import Callable, Tuple

import pytest

from datamover.file_functions.fs_mock import FS
from datamover.mover.mover_thread import FileMoveThread
from datamover.mover.thread_factory import create_file_move_thread
from datamover.protocols import SafeFileMover, SleepCallable
from tests.test_utils.logging_helpers import find_log_record

# --- Constants for patch locations and logger name ---
FACTORY_MODULE_PATH = "datamover.mover.thread_factory"
PROCESS_SINGLE_LOGGER_NAME = FACTORY_MODULE_PATH
FILE_MOVE_THREAD_CLASS_PATH = f"{FACTORY_MODULE_PATH}.FileMoveThread"
RESOLVE_DIR_FUNC_PATH = f"{FACTORY_MODULE_PATH}.resolve_and_validate_directory"
DEFAULT_MOVER_FUNC_PATH = f"{FACTORY_MODULE_PATH}.move_file_safely_impl"
DEFAULT_SLEEP_FUNC_PATH = f"{FACTORY_MODULE_PATH}.time.sleep"


# --- Fixtures ---
@pytest.fixture
def test_source_dir_path() -> Path:
    return Path("raw/source_for_test")


@pytest.fixture
def test_worker_dir_path() -> Path:
    return Path("raw/destination_for_test")


@pytest.fixture
def test_poll_interval() -> float:
    return 0.05


@pytest.fixture
def source_queue() -> MagicMock:
    return MagicMock(spec=Queue)


@pytest.fixture
def stop_event() -> threading.Event:
    return threading.Event()


@pytest.fixture
def mock_fs() -> MagicMock:
    return MagicMock(spec=FS)


@pytest.fixture
def mock_sleep_func() -> MagicMock:
    return MagicMock(spec=SleepCallable)


@pytest.fixture
def resolved_src_dir() -> Path:
    return Path("/resolved/source")


@pytest.fixture
def resolved_dst_dir_name() -> str:
    return "destination_folder_resolved"


@pytest.fixture
def mock_resolved_dst_dir(resolved_dst_dir_name) -> MagicMock:
    m = MagicMock(spec=Path)
    m.name = resolved_dst_dir_name
    m.__truediv__.side_effect = lambda other: Path(f"/resolved_mock_dest/{other}")
    return m


@pytest.fixture
def filemove_ctor(monkeypatch) -> MagicMock:
    ctor = MagicMock(spec=FileMoveThread)
    monkeypatch.setattr(FILE_MOVE_THREAD_CLASS_PATH, ctor)
    return ctor


@pytest.fixture(autouse=True)
def resolve_dir(monkeypatch, resolved_src_dir, mock_resolved_dst_dir) -> MagicMock:
    fn = MagicMock()
    fn.side_effect = [resolved_src_dir, mock_resolved_dst_dir]
    monkeypatch.setattr(RESOLVE_DIR_FUNC_PATH, fn)
    return fn


@pytest.fixture
def process_single_factory(
    test_source_dir_path: Path,
    test_worker_dir_path: Path,
    test_poll_interval: float,
    source_queue: MagicMock,
    stop_event: threading.Event,
    mock_fs: MagicMock,
    mock_sleep_func: MagicMock,
    mock_resolved_dst_dir: MagicMock,
    filemove_ctor: MagicMock,
) -> Callable[[SafeFileMover], Tuple[Callable[[Path], None], str]]:
    def _make(mover_func: SafeFileMover):
        create_file_move_thread(
            source_dir_path=test_source_dir_path,
            worker_dir_path=test_worker_dir_path,
            poll_interval_seconds=test_poll_interval,
            source_queue=source_queue,
            stop_event=stop_event,
            fs=mock_fs,
            file_mover_func=mover_func,
            sleep_func=mock_sleep_func,
        )
        kwargs = filemove_ctor.call_args[1]
        proc_fn = kwargs["process_single"]
        thread_name = f"FileMover-{mock_resolved_dst_dir.name}"
        return proc_fn, thread_name

    return _make


# --- Tests ---


def test_create_thread_successful_construction(
    test_source_dir_path: Path,
    test_worker_dir_path: Path,
    test_poll_interval: float,
    source_queue: MagicMock,
    stop_event: threading.Event,
    mock_fs: MagicMock,
    mock_sleep_func: MagicMock,
    mock_resolved_dst_dir: MagicMock,
    filemove_ctor: MagicMock,
    resolve_dir: MagicMock,
):
    mover_func = MagicMock(spec=SafeFileMover)

    thread = create_file_move_thread(
        source_dir_path=test_source_dir_path,
        worker_dir_path=test_worker_dir_path,
        poll_interval_seconds=test_poll_interval,
        source_queue=source_queue,
        stop_event=stop_event,
        fs=mock_fs,
        file_mover_func=mover_func,
        sleep_func=mock_sleep_func,
    )

    assert thread is filemove_ctor.return_value
    resolve_dir.assert_has_calls(
        [
            call(
                raw_path=test_source_dir_path,
                fs=mock_fs,
                dir_label="source for FileMover",
            ),
            call(
                raw_path=test_worker_dir_path,
                fs=mock_fs,
                dir_label="destination for FileMover (worker)",
            ),
        ],
        any_order=False,
    )
    assert resolve_dir.call_count == 2

    expected_name = f"FileMover-{mock_resolved_dst_dir.name}"
    _, kwargs = filemove_ctor.call_args
    assert kwargs["source_queue"] is source_queue
    assert callable(kwargs["process_single"])
    assert kwargs["stop_event"] is stop_event
    assert kwargs["sleep_func"] is mock_sleep_func
    assert kwargs["name"] == expected_name
    assert kwargs["poll_interval"] == test_poll_interval


def test_create_thread_uses_default_file_mover_and_sleep(
    test_source_dir_path: Path,
    test_worker_dir_path: Path,
    test_poll_interval: float,
    source_queue: MagicMock,
    stop_event: threading.Event,
    mock_fs: MagicMock,
    mock_resolved_dst_dir: MagicMock,
    resolved_src_dir: Path,
    filemove_ctor: MagicMock,
):
    with (
        patch(DEFAULT_MOVER_FUNC_PATH) as mock_default_mover,
        patch(DEFAULT_SLEEP_FUNC_PATH) as mock_default_sleep,
    ):
        create_file_move_thread(
            source_dir_path=test_source_dir_path,
            worker_dir_path=test_worker_dir_path,
            poll_interval_seconds=test_poll_interval,
            source_queue=source_queue,
            stop_event=stop_event,
            fs=mock_fs,
        )

    _, kwargs = filemove_ctor.call_args
    assert kwargs["sleep_func"] is mock_default_sleep
    assert kwargs["poll_interval"] == test_poll_interval

    proc_fn = kwargs["process_single"]
    test_path = Path("some_file_to_process.txt")
    proc_fn(test_path)
    mock_default_mover.assert_called_once_with(
        source_path_raw=test_path,
        expected_source_dir=resolved_src_dir,
        destination_dir=mock_resolved_dst_dir,
        fs=mock_fs,
    )


def test_process_single_item_success_logging(
    process_single_factory,
    mock_resolved_dst_dir: MagicMock,
    caplog,
):
    final_dest = mock_resolved_dst_dir / "source_file.txt"
    mover_mock = MagicMock(spec=SafeFileMover, return_value=final_dest)

    proc_fn, thread_name = process_single_factory(mover_mock)
    caplog.set_level(logging.DEBUG, logger=PROCESS_SINGLE_LOGGER_NAME)

    proc_fn(Path("source_file.txt"))

    mover_mock.assert_called_once()
    log = find_log_record(
        caplog,
        logging.DEBUG,
        [
            thread_name,
            "Successfully processed and moved",
            "source_file.txt",
            str(final_dest),
        ],
    )
    assert log is not None


def test_process_single_item_failure_mover_returns_none_logging(
    process_single_factory,
    caplog,
):
    mover_mock = MagicMock(spec=SafeFileMover, return_value=None)

    proc_fn, thread_name = process_single_factory(mover_mock)
    caplog.set_level(logging.WARNING, logger=PROCESS_SINGLE_LOGGER_NAME)

    proc_fn(Path("unmovable_file.txt"))

    mover_mock.assert_called_once()
    log = find_log_record(
        caplog,
        logging.WARNING,
        [thread_name, "Failed to process 'unmovable_file.txt'", "See previous logs"],
    )
    assert log is not None


def test_process_single_item_unexpected_exception_in_mover_logging(
    process_single_factory,
    caplog,
):
    err = RuntimeError("Kaboom!")
    mover_mock = MagicMock(spec=SafeFileMover, side_effect=err)

    proc_fn, thread_name = process_single_factory(mover_mock)
    caplog.set_level(logging.ERROR, logger=PROCESS_SINGLE_LOGGER_NAME)

    proc_fn(Path("exploding_file.txt"))

    mover_mock.assert_called_once()
    log = find_log_record(
        caplog,
        logging.ERROR,
        [
            thread_name,
            "Unexpected critical error during file processing for 'exploding_file.txt'",
            "Kaboom!",
        ],
    )
    assert log is not None
    assert log.exc_info is not None
    _, exc_val, _ = log.exc_info
    assert exc_val is err


def test_resolve_directory_raises_exception_propagates(
    test_source_dir_path: Path,
    test_worker_dir_path: Path,
    test_poll_interval: float,
    source_queue: MagicMock,
    stop_event: threading.Event,
    mock_fs: MagicMock,
    mock_sleep_func: MagicMock,
    filemove_ctor: MagicMock,
    resolve_dir: MagicMock,
):
    expected_exc = ValueError("Invalid directory path for test")
    resolve_dir.side_effect = expected_exc

    with pytest.raises(ValueError) as exc:
        create_file_move_thread(
            source_dir_path=test_source_dir_path,
            worker_dir_path=test_worker_dir_path,
            poll_interval_seconds=test_poll_interval,
            source_queue=source_queue,
            stop_event=stop_event,
            fs=mock_fs,
            file_mover_func=MagicMock(spec=SafeFileMover),
            sleep_func=mock_sleep_func,
        )

    assert exc.value is expected_exc
    filemove_ctor.assert_not_called()
