import logging
import os
import queue
import time
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, call

import pytest

# --- Application Imports ---
from datamover.file_functions.fs_mock import FS  # For real_fs type hint
from datamover.tailer.data_class import (
    InitialFoundEvent,
    CreatedEvent,
    ModifiedEvent,
    DeletedEvent,
    MovedEvent,
)
from datamover.tailer.tail_processor import TailProcessor

# --- Shared Test Utils ---
from tests.test_utils.fs_helpers import create_and_stamp_real_fs

logger = logging.getLogger(__name__)


# --- Fixtures for TailProcessor Integration ---


@pytest.fixture
def integration_watched_dir(tmp_path: Path) -> Path:
    """Provides a real temporary directory that TailProcessor will 'watch' (via events)."""
    watch_dir = tmp_path / "tailer_watched_dir_integration"
    watch_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created integration watched directory: {watch_dir}")
    return watch_dir


@pytest.fixture
def mock_move_queue_integration() -> MagicMock:
    """Provides a MagicMock for the move_queue dependency of TailProcessor."""
    return MagicMock(spec=queue.Queue, name="integration_move_queue")


@pytest.fixture
def integration_tail_processor(
    real_fs: FS,
    mock_move_queue_integration: MagicMock,
) -> TailProcessor:
    """
    Provides a TailProcessor instance with real_fs.
    It will use the real parse_log_line and flush_buffer imported within its own module.
    """
    processor = TailProcessor(
        fs=real_fs,
        move_queue=mock_move_queue_integration,
        move_queue_name="integration_tailer_move_q",
    )
    logger.debug(
        "Created TailProcessor for integration test with real_fs and real helpers."
    )
    return processor


@pytest.fixture
def caplog_debug_all(caplog: pytest.LogCaptureFixture):
    """Configures caplog fixture to capture DEBUG level logs from all loggers for the test."""
    caplog.set_level(logging.DEBUG)
    return caplog


# --- Integration Test Cases ---
@pytest.mark.integration
class TestTailProcessorTrueIntegration:
    @pytest.mark.parametrize(
        "file_setup_info, event_path_rel, expected_pos_rel, expected_buf_rel, scenario_id",
        [
            (  # File exists with size
                {"content": b"line1\nline2\n", "mtime_offset": -10},
                "initial_exists.log",
                {"initial_exists.log": 12},
                {"initial_exists.log": b""},
                "file_exists_with_size",
            ),
            (  # File exists empty
                {"content": b"", "mtime_offset": -10},
                "initial_empty.log",
                {"initial_empty.log": 0},
                {"initial_empty.log": b""},
                "file_exists_empty",
            ),
            (  # File does not exist on FS
                None,  # No file setup needed
                "initial_missing.log",
                {},
                {},
                "file_missing",
            ),
        ],
    )
    def test_initial_found_event_handling(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        file_setup_info: Optional[dict[str, Any]],
        event_path_rel: str,
        expected_pos_rel: dict[str, int],
        expected_buf_rel: dict[str, bytes],
        scenario_id: str,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}[{scenario_id}]")
        processor = integration_tail_processor

        actual_event_path_abs = integration_watched_dir / event_path_rel

        expected_positions_abs = {
            integration_watched_dir / k: v for k, v in expected_pos_rel.items()
        }
        expected_buffers_abs = {
            integration_watched_dir / k: v for k, v in expected_buf_rel.items()
        }

        if file_setup_info:
            content = file_setup_info["content"]
            create_and_stamp_real_fs(
                real_fs,
                actual_event_path_abs,
                len(content),
                time.time() + file_setup_info["mtime_offset"],
                initial_create=True,
            )
            if content:  # Write specific content
                with real_fs.open(actual_event_path_abs, "wb") as f:
                    f.write(content)
        elif real_fs.exists(
            actual_event_path_abs
        ):  # Ensure it's gone if test expects missing
            os.remove(actual_event_path_abs)

        event = InitialFoundEvent(path=str(actual_event_path_abs))
        processor.process_event(event)

        assert processor.file_positions == expected_positions_abs
        assert processor.file_buffers == expected_buffers_abs
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info(f"Scenario '{scenario_id}' passed.")

    def test_initial_found_stat_error_not_tracked(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        mocker: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor

        file_rel_path = "initial_stat_error.log"
        target_file_path = integration_watched_dir / file_rel_path

        create_and_stamp_real_fs(real_fs, target_file_path, 10, time.time() - 10)

        # Store original os.stat to call if needed, though not strictly for this side_effect's current logic
        # original_os_stat = os.stat # Not needed if side_effect only handles the target path

        def patched_os_stat_side_effect(path_to_stat_str: str):
            if Path(path_to_stat_str) == target_file_path:
                test_logger.debug(
                    f"Patched os.stat: Raising OSError for {target_file_path}"
                )
                raise OSError("Simulated stat failure for test")
            # If we need to call original for other paths:
            # return original_os_stat(path_to_stat_str)
            # Otherwise, this will implicitly raise if another path is stat'd and not handled.
            # For this test, we expect only target_file_path to be stat'd in the error path.
            pytest.fail(
                f"Patched os.stat unexpectedly called for path: {path_to_stat_str}"
            )

        # Patch 'os.stat' without 'with'. mocker handles teardown.
        mocker.patch(
            "datamover.file_functions.fs_mock.os.stat",
            side_effect=patched_os_stat_side_effect,
        )

        event = InitialFoundEvent(path=str(target_file_path))
        processor.process_event(event)

        assert not processor.file_positions
        assert not processor.file_buffers
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info(
            "Test Finished: Initial file with stat error correctly not tracked."
        )

    def test_created_event_new_file_with_content_tracked_at_eof(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor

        file_rel_path = "created_with_content.log"
        target_file_path = integration_watched_dir / file_rel_path
        content = b"Content written before create event.\n"
        size = len(content)

        create_and_stamp_real_fs(real_fs, target_file_path, size, time.time() - 5)
        with real_fs.open(target_file_path, "wb") as f:
            f.write(content)

        event = CreatedEvent(path=str(target_file_path))
        processor.process_event(event)

        assert processor.file_positions == {target_file_path: size}
        assert processor.file_buffers == {target_file_path: b""}
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info(
            "Test Finished: Created file with content correctly tracked at EOF."
        )

    def test_modified_appended_data_is_read_flushed_parsed_and_queued(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor

        file_rel_path = "appended_real_parse.log"
        target_file_path = integration_watched_dir / file_rel_path

        initial_content = (
            b"timestamp,filepath,sha256\n"  # Header or previous valid line
        )
        # This is the line that will be parsed by the real parse_log_line
        # Ensure it's a valid format that your parse_log_line expects.
        # Example valid line for your parse_log_line:
        valid_log_line_content = "1678886400,/srv/data/real_file.dat,abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        appended_data_bytes = (valid_log_line_content + "\n").encode("utf-8")

        create_and_stamp_real_fs(
            real_fs, target_file_path, len(initial_content), time.time() - 20
        )
        with real_fs.open(target_file_path, "wb") as f:
            f.write(initial_content)

        processor.file_positions[target_file_path] = len(initial_content)
        processor.file_buffers[target_file_path] = b""
        test_logger.debug(
            f"Initial state for {target_file_path}: pos={len(initial_content)}, buffer empty."
        )

        time.sleep(0.01)
        current_mtime = time.time()
        with real_fs.open(target_file_path, "ab") as f:
            f.write(appended_data_bytes)
        os.utime(target_file_path, (current_mtime, current_mtime))

        new_total_size = len(initial_content) + len(appended_data_bytes)
        assert real_fs.stat(target_file_path).st_size == new_total_size

        event = ModifiedEvent(path=str(target_file_path))
        processor.process_event(event)

        assert processor.file_positions[target_file_path] == new_total_size
        # The real flush_buffer will return ([], b"") if a complete line was consumed
        assert processor.file_buffers[target_file_path] == b"", (
            "Buffer should be empty after full line processing"
        )

        expected_queued_path = Path(
            "/srv/data/real_file.dat"
        )  # From valid_log_line_content
        mock_move_queue_integration.put.assert_called_once_with(
            expected_queued_path, block=True, timeout=None
        )
        test_logger.info(
            "Test Finished: Appended data processed via real helpers and queued."
        )

    def test_modified_no_size_change_no_action(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor
        file_rel_path = "no_change_integ.log"
        target_file_path = integration_watched_dir / file_rel_path
        initial_content = b"data"
        initial_size = len(initial_content)

        create_and_stamp_real_fs(
            real_fs, target_file_path, initial_size, time.time() - 10
        )
        with real_fs.open(target_file_path, "wb") as f:
            f.write(initial_content)
        processor.file_positions[target_file_path] = initial_size
        processor.file_buffers[target_file_path] = b"test_buffer"

        os.utime(target_file_path, (time.time(), time.time()))  # Touch mtime

        event = ModifiedEvent(path=str(target_file_path))
        processor.process_event(event)

        assert processor.file_positions[target_file_path] == initial_size
        assert processor.file_buffers[target_file_path] == b"test_buffer"
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info("Test Finished: No size change, no action.")

    def test_modified_truncated_file_resets_state(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor
        file_rel_path = "truncated_integ.log"
        target_file_path = integration_watched_dir / file_rel_path
        original_content = b"This is a long line that will be truncated by the test."
        new_shorter_content = b"Shortened."
        new_size = len(new_shorter_content)

        create_and_stamp_real_fs(
            real_fs, target_file_path, len(original_content), time.time() - 10
        )
        with real_fs.open(target_file_path, "wb") as f:
            f.write(original_content)
        processor.file_positions[target_file_path] = len(original_content)
        processor.file_buffers[target_file_path] = b"buffer_content_before_truncate"

        time.sleep(0.01)
        current_mtime = time.time()
        with real_fs.open(target_file_path, "wb") as f:
            f.write(new_shorter_content)
        os.utime(target_file_path, (current_mtime, current_mtime))

        event = ModifiedEvent(path=str(target_file_path))
        processor.process_event(event)

        assert processor.file_positions[target_file_path] == new_size
        assert processor.file_buffers[target_file_path] == b""
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info("Test Finished: Truncated file state reset.")

    def test_deleted_event_removes_tracking(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor
        file_rel_path = "deleted_integ.log"
        target_file_path = integration_watched_dir / file_rel_path

        create_and_stamp_real_fs(real_fs, target_file_path, 50, time.time() - 10)
        processor.file_positions[target_file_path] = 50
        processor.file_buffers[target_file_path] = b"data"

        os.remove(target_file_path)  # Actually delete from real FS

        event = DeletedEvent(path=str(target_file_path))
        processor.process_event(event)

        assert target_file_path not in processor.file_positions
        assert target_file_path not in processor.file_buffers
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info("Test Finished: Deleted event removed tracking.")

    def test_moved_event_source_deleted_destination_tracked(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor
        src_rel = "source_moved_integ.log"
        dst_rel = "dest_moved_integ.log"
        src_abs = integration_watched_dir / src_rel
        dst_abs = integration_watched_dir / dst_rel
        src_content = b"Moved content"
        src_size = len(src_content)

        create_and_stamp_real_fs(real_fs, src_abs, src_size, time.time() - 10)
        with real_fs.open(src_abs, "wb") as f:
            f.write(src_content)
        processor.file_positions[src_abs] = src_size
        processor.file_buffers[src_abs] = b"src_buf"

        real_fs.move(src_abs, dst_abs)  # Actual move
        # Update mtime of dst if move doesn't preserve it reliably or if test cares
        dst_mtime = time.time() - 5
        os.utime(dst_abs, (dst_mtime, dst_mtime))
        dst_size_after_move = real_fs.stat(dst_abs).st_size

        event = MovedEvent(src_path=str(src_abs), dest_path=str(dst_abs))
        processor.process_event(event)

        assert src_abs not in processor.file_positions
        assert src_abs not in processor.file_buffers
        assert processor.file_positions == {dst_abs: dst_size_after_move}
        assert processor.file_buffers == {dst_abs: b""}
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info("Test Finished: Moved event handled.")

    def test_modified_event_late_sync_untracked_file(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor
        file_rel_path = "late_sync_integ.log"
        target_file_path = integration_watched_dir / file_rel_path
        content = b"Late sync content\n"
        size = len(content)

        assert target_file_path not in processor.file_positions  # Pre-condition

        create_and_stamp_real_fs(real_fs, target_file_path, size, time.time() - 5)
        with real_fs.open(target_file_path, "wb") as f:
            f.write(content)

        event = ModifiedEvent(path=str(target_file_path))
        processor.process_event(event)

        assert processor.file_positions == {target_file_path: size}
        assert processor.file_buffers == {target_file_path: b""}
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info("Test Finished: Late sync for modified untracked file.")

    def test_modified_event_handles_fs_open_error_integration(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        mocker: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor
        file_rel_path = "open_error_integ.log"
        target_file_path = integration_watched_dir / file_rel_path

        initial_content = b"abc"
        initial_size = len(initial_content)
        appended_data_simulated_size = b"def"

        create_and_stamp_real_fs(
            real_fs, target_file_path, initial_size, time.time() - 10
        )
        with real_fs.open(target_file_path, "wb") as f:
            f.write(initial_content)
        processor.file_positions[target_file_path] = initial_size
        processor.file_buffers[target_file_path] = b"initial_buf"

        # Store original os.stat if you intend to call it for non-target paths
        original_os_stat = os.stat

        def patched_os_stat_reports_growth(path_to_stat_str: str):
            if Path(path_to_stat_str) == target_file_path:
                test_logger.debug(
                    f"Patched os.stat: Reporting growth for {target_file_path}"
                )
                mock_stat_val = MagicMock(spec=os.stat_result)
                mock_stat_val.st_size = initial_size + len(appended_data_simulated_size)
                mock_stat_val.st_mtime = time.time()
                return mock_stat_val
            return original_os_stat(path_to_stat_str)  # Call original for other paths

        # Apply patches sequentially. They will both be active.
        mocker.patch(
            "datamover.file_functions.fs_mock.os.stat",
            side_effect=patched_os_stat_reports_growth,
        )
        mocker.patch(
            "datamover.file_functions.fs_mock.open",  # Path to 'open' used by _default_open
            side_effect=OSError("Permission denied to open for test"),
            create=True,
        )  # create=True is often needed for patching builtins

        event = ModifiedEvent(path=str(target_file_path))
        processor.process_event(event)

        assert processor.file_positions[target_file_path] == initial_size
        assert processor.file_buffers[target_file_path] == b"initial_buf"
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info("Test Finished: Modified event with FS open error handled.")

    def test_created_event_file_modified_before_processing(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,  # To assert no puts from initial state
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor

        file_rel_path = "created_then_modified_quickly.log"
        target_file_path = integration_watched_dir / file_rel_path

        # 1. File is "created" (imagine watchdog saw this)
        initial_content_at_creation = b"original_line\n"
        create_and_stamp_real_fs(
            real_fs,
            target_file_path,
            len(initial_content_at_creation),
            time.time() - 10,
        )
        with real_fs.open(target_file_path, "wb") as f:
            f.write(initial_content_at_creation)

        # 2. File is "modified" *before* TailProcessor gets the CreatedEvent for the original creation
        appended_content = b"appended_quickly\n"
        time.sleep(0.01)  # Ensure different mtime
        current_mtime = time.time() - 5
        with real_fs.open(target_file_path, "ab") as f:
            f.write(appended_content)
        os.utime(target_file_path, (current_mtime, current_mtime))

        final_size_on_fs = len(initial_content_at_creation) + len(appended_content)
        assert (
            real_fs.stat(target_file_path).st_size == final_size_on_fs
        )  # Verify FS state

        # 3. Now, TailProcessor processes the (delayed) CreatedEvent
        event = CreatedEvent(path=str(target_file_path))
        processor.process_event(event)

        # Expected: _handle_track is called, it stats the file and finds its *current* (final) size.
        # It should track from the current EOF.
        assert processor.file_positions == {target_file_path: final_size_on_fs}
        assert processor.file_buffers == {target_file_path: b""}  # No backfill
        mock_move_queue_integration.put.assert_not_called()  # CreatedEvent doesn't process content
        test_logger.info(
            "Test Finished: CreatedEvent for a pre-modified file correctly tracked at final EOF."
        )

    def test_created_event_file_deleted_before_processing(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        processor = integration_tail_processor

        file_rel_path = "created_then_deleted_quickly.log"
        target_file_path = integration_watched_dir / file_rel_path

        # 1. File is "created"
        content_at_creation = b"short_lived\n"
        create_and_stamp_real_fs(
            real_fs, target_file_path, len(content_at_creation), time.time() - 10
        )
        with real_fs.open(target_file_path, "wb") as f:
            f.write(content_at_creation)

        # 2. File is "deleted" *before* TailProcessor gets the CreatedEvent
        os.remove(target_file_path)
        assert not real_fs.exists(target_file_path)  # Verify FS state

        # 3. Now, TailProcessor processes the (delayed) CreatedEvent
        event = CreatedEvent(path=str(target_file_path))
        processor.process_event(event)

        # Expected: _handle_track is called, fs.exists() returns False. File is not tracked.
        assert target_file_path not in processor.file_positions
        assert target_file_path not in processor.file_buffers
        mock_move_queue_integration.put.assert_not_called()
        test_logger.info(
            "Test Finished: CreatedEvent for a pre-deleted file correctly not tracked."
        )

    def test_multiple_appends_processed_correctly(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,  # This should be your actual FS() instance via fixture
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        test_logger.info("Starting test: multiple appends processed correctly")
        processor = integration_tail_processor

        file_rel_path = "multi_append.log"
        target_file_path = integration_watched_dir / file_rel_path

        # Initial setup: file exists and is tracked at EOF 0
        create_and_stamp_real_fs(
            real_fs, target_file_path, 0, time.time() - 30, initial_create=True
        )
        processor.file_positions[target_file_path] = 0
        processor.file_buffers[target_file_path] = b""
        test_logger.debug(f"Initial state for {target_file_path}: pos=0, buffer empty.")

        # Define valid 64-char hex dummy hashes
        hash_a = "a1" * 32
        hash_b = "b2" * 32
        hash_c = "c3" * 32

        appends_config = [
            {
                "line_content": f"1678886401,/srv/data/fileA.dat,{hash_a}",
                "expected_path": Path("/srv/data/fileA.dat"),
                "partial_suffix": b"",
            },
            {
                "line_content": f"1678886402,/srv/data/fileB.dat,{hash_b}",
                "expected_path": Path("/srv/data/fileB.dat"),
                "partial_suffix": b"",
            },
            {
                "line_content": f"1678886403,/srv/data/fileC.dat,{hash_c}",
                "expected_path": Path("/srv/data/fileC.dat"),
                "partial_suffix": b"part_remains",
            },
        ]

        current_file_size = 0
        expected_put_calls_list = []

        for i, append_item in enumerate(appends_config):
            data_to_append = (append_item["line_content"] + "\n").encode(
                "utf-8"
            ) + append_item["partial_suffix"]
            expected_path_queued = append_item["expected_path"]

            test_logger.debug(
                f"Append #{i + 1}: writing '{data_to_append!r}' (len {len(data_to_append)})"
            )
            time.sleep(0.01)  # Ensure mtime changes distinctly
            current_mtime = time.time() - (
                10 - i * 2
            )  # Ensure mtimes are somewhat spaced

            # Append data to the real file
            with real_fs.open(target_file_path, "ab") as f:
                f.write(data_to_append)
            os.utime(target_file_path, (current_mtime, current_mtime))  # Update mtime

            current_file_size += len(data_to_append)
            # Verify FS state immediately after write
            assert real_fs.stat(target_file_path).st_size == current_file_size, (
                f"FS size mismatch after append {i + 1}"
            )

            event = ModifiedEvent(path=str(target_file_path))
            processor.process_event(event)

            # Add to expected calls if a full line (ending with \n before partial_suffix) was processed
            if append_item[
                "line_content"
            ]:  # All your line_content strings are non-empty
                expected_put_calls_list.append(
                    call(expected_path_queued, block=True, timeout=None)
                )

            test_logger.debug(
                f"After append #{i + 1}: pos={processor.file_positions.get(target_file_path)}, "
                f"buffer='{processor.file_buffers.get(target_file_path)!r}'"
            )

        # Final Assertions
        assert processor.file_positions.get(target_file_path) == current_file_size
        assert (
            processor.file_buffers.get(target_file_path)
            == appends_config[-1]["partial_suffix"]
        )

        assert mock_move_queue_integration.put.call_count == len(
            expected_put_calls_list
        )
        if expected_put_calls_list:
            mock_move_queue_integration.put.assert_has_calls(
                expected_put_calls_list, any_order=False
            )

        test_logger.info("Test Finished: Multiple appends processed correctly.")

    def test_buffer_concatenation_across_appends(
        self,
        integration_tail_processor: TailProcessor,
        real_fs: FS,  # This should be your actual FS() instance via fixture
        integration_watched_dir: Path,
        mock_move_queue_integration: MagicMock,
        request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        test_logger.info("Starting test: buffer concatenation across appends")
        processor = integration_tail_processor

        file_rel_path = "buffer_concat_test.log"
        target_file_path = integration_watched_dir / file_rel_path

        # Define valid 64-char hex dummy hashes
        hash1_complete = "1a" * 32
        hash2_complete = "2b" * 32

        # Initial setup: file exists and is tracked at EOF 0
        create_and_stamp_real_fs(
            real_fs, target_file_path, 0, time.time() - 30, initial_create=True
        )
        processor.file_positions[target_file_path] = 0
        processor.file_buffers[target_file_path] = b""
        test_logger.debug(f"Initial state for {target_file_path}: pos=0, buffer empty.")

        # --- Append 1: A partial line ---
        # Content: "1700000000,/path/one,<first_half_of_hash1>"
        append1_data_str = f"1700000000,/path/one,{hash1_complete[:32]}"  # No newline
        append1_data_bytes = append1_data_str.encode("utf-8")

        current_mtime1 = time.time() - 20
        with real_fs.open(target_file_path, "ab") as f:
            f.write(append1_data_bytes)
        os.utime(target_file_path, (current_mtime1, current_mtime1))
        test_logger.debug(f"Append 1: Wrote '{append1_data_bytes!r}'")

        event1 = ModifiedEvent(path=str(target_file_path))
        processor.process_event(event1)

        assert processor.file_positions.get(target_file_path) == len(append1_data_bytes)
        assert processor.file_buffers.get(target_file_path) == append1_data_bytes
        mock_move_queue_integration.put.assert_not_called()  # No full line processed yet
        test_logger.debug(
            f"After append 1: pos={processor.file_positions.get(target_file_path)}, buffer='{processor.file_buffers.get(target_file_path)!r}'"
        )

        # --- Append 2: Completes the first line, adds a new full line, and a new partial line ---
        # Line 1 completed: "1700000000,/path/one,<hash1_complete>"
        # Line 2 complete:  "1700000001,/path/two,<hash2_complete>"
        # Remaining partial: "final_incomplete_bit"
        append2_data_str_part1 = hash1_complete[32:]  # Second half of hash1
        append2_data_str_line2 = f"\n1700000001,/path/two,{hash2_complete}\n"
        append2_data_str_partial3 = "final_incomplete_bit"
        append2_data_bytes = (
            append2_data_str_part1 + append2_data_str_line2 + append2_data_str_partial3
        ).encode("utf-8")

        time.sleep(0.01)  # Ensure mtime changes
        current_mtime2 = time.time() - 10
        with real_fs.open(target_file_path, "ab") as f:
            f.write(append2_data_bytes)
        os.utime(target_file_path, (current_mtime2, current_mtime2))
        test_logger.debug(f"Append 2: Wrote '{append2_data_bytes!r}'")

        event2 = ModifiedEvent(path=str(target_file_path))
        processor.process_event(event2)

        new_total_size = len(append1_data_bytes) + len(append2_data_bytes)
        assert processor.file_positions.get(target_file_path) == new_total_size
        assert processor.file_buffers.get(
            target_file_path
        ) == append2_data_str_partial3.encode("utf-8")

        expected_put_calls = [
            call(Path("/path/one"), block=True, timeout=None),
            call(Path("/path/two"), block=True, timeout=None),
        ]
        assert mock_move_queue_integration.put.call_count == 2
        mock_move_queue_integration.put.assert_has_calls(
            expected_put_calls, any_order=False
        )

        test_logger.info("Test Finished: Buffer concatenation across appends verified.")
