import logging
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest

from datamover.queues.queue_functions import QueuePutError
from datamover.tailer.data_class import (
    TailerQueueEvent,
    InitialFoundEvent,
    CreatedEvent,
    ModifiedEvent,
    DeletedEvent,
    MovedEvent,
)
from datamover.tailer.parse_csv_line import (
    ParsedLine,
    LineParsingError,
)
from datamover.tailer.tail_processor import TailProcessor
from tests.test_utils.logging_helpers import find_log_record

# Paths for patching module-level functions used by TailProcessor
FLUSH_BUFFER_PATH = "datamover.tailer.tail_processor.flush_buffer"
PARSE_LOG_LINE_PATH = "datamover.tailer.tail_processor.parse_log_line"
SAFE_PUT_PATH = "datamover.tailer.tail_processor.safe_put"


# --- Fixtures ---


@pytest.fixture
def configured_mock_fs(
    mock_fs: MagicMock,
) -> MagicMock:  # mock_fs comes from conftest.py
    """
    Takes the bare mock_fs from conftest (which is MagicMock(spec=FS))
    and configures its attributes (like open, stat, exists) to be callable
    mocks with appropriate structures for TailProcessor's usage.
    """
    # Setup for fs.open() to return a context manager yielding a mock file handle
    mock_file_handle = MagicMock(name="mock_file_handle")
    mock_file_handle.seek = MagicMock(name="seek")
    mock_file_handle.read = MagicMock(name="read")
    mock_file_handle.tell = MagicMock(name="tell")

    mock_context_manager = MagicMock(name="mock_context_manager")
    mock_context_manager.__enter__.return_value = mock_file_handle
    mock_context_manager.__exit__.return_value = None

    # Configure the mock_fs instance received from conftest
    mock_fs.open = MagicMock(return_value=mock_context_manager, name="fs_open_mock")

    # Ensure stat and exists are callable mocks. If mock_fs is already a MagicMock,
    # accessing these attributes will create them as MagicMocks if they don't exist.
    # We just ensure they are there if tests need to set return_value on them directly.
    # No need to re-assign if they are already mocks, just ensure they exist for setup.
    _ = mock_fs.stat  # Access to ensure it's a MagicMock if not already customized
    _ = mock_fs.exists  # Access to ensure it's a MagicMock

    return mock_fs


@pytest.fixture
def mock_move_queue() -> MagicMock:
    """Provides a MagicMock simulating the output Queue."""
    return MagicMock(spec=Queue, name="move_queue_mock")


@pytest.fixture
def processor(
    configured_mock_fs: MagicMock, mock_move_queue: MagicMock
) -> TailProcessor:
    """Provides a fresh TailProcessor instance with configured mocked dependencies."""
    return TailProcessor(
        fs=configured_mock_fs,
        move_queue=mock_move_queue,
        move_queue_name="unit_test_q",
    )


@pytest.fixture
def processor_with_custom_enqueuer(
    configured_mock_fs: MagicMock, mock_move_queue: MagicMock
):
    """Provides a TailProcessor with a custom (mocked) enqueuer function."""
    mock_custom_enqueuer = MagicMock(name="custom_enqueuer_mock")
    proc = TailProcessor(
        fs=configured_mock_fs,
        move_queue=mock_move_queue,
        move_queue_name="custom_enqueue_q",
        enqueuer=mock_custom_enqueuer,
    )
    return proc, mock_custom_enqueuer


# Helper to create a mock stat result
def create_mock_stat_result(size: int) -> MagicMock:
    mock_stat = MagicMock()
    mock_stat.st_size = size
    return mock_stat


# Helper to create a mock ParsedLine
def create_mock_parsed_line(filepath_str: str) -> ParsedLine:
    # Using a real ParsedLine instance is often better unless mocking specific behavior of ParsedLine
    return ParsedLine(timestamp=123456, filepath=filepath_str, sha256_hash="a" * 64)


# --- Test Class ---
@patch(SAFE_PUT_PATH, autospec=True)
@patch(FLUSH_BUFFER_PATH, autospec=True)
@patch(PARSE_LOG_LINE_PATH, autospec=True)
class TestTailProcessorUnit:
    # === Requirement #1: Initial Tracking & Creation ===

    def test_initial_found_event_tracks_existing_file_at_eof(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        path_str, path_obj, file_size = "/logs/app.log", Path("/logs/app.log"), 1024
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(file_size)

        processor.process_event(InitialFoundEvent(path=path_str))

        configured_mock_fs.exists.assert_called_once_with(path_obj)
        configured_mock_fs.stat.assert_called_once_with(path_obj)
        configured_mock_fs.open.assert_not_called()
        mock_parse.assert_not_called()
        mock_flush.assert_not_called()
        mock_safe_put.assert_not_called()
        assert processor.file_positions == {path_obj: file_size}
        assert processor.file_buffers == {path_obj: b""}
        assert find_log_record(
            caplog,
            logging.INFO,
            [f"Initial track at EOF ({file_size} bytes): {path_obj}"],
        )

    def test_initial_found_event_ignores_non_existent_file(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)
        path_str, path_obj = "/logs/missing.log", Path("/logs/missing.log")
        configured_mock_fs.exists.return_value = False

        processor.process_event(InitialFoundEvent(path=path_str))

        configured_mock_fs.exists.assert_called_once_with(path_obj)
        configured_mock_fs.stat.assert_not_called()
        assert not processor.file_positions
        assert not processor.file_buffers
        mock_safe_put.assert_not_called()
        assert find_log_record(
            caplog, logging.DEBUG, [f"file not found {path_obj}", "not tracking"]
        )

    def test_initial_found_event_ignores_file_on_stat_error(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING)
        path_str, path_obj = "/logs/stat_error.log", Path("/logs/stat_error.log")
        os_error = OSError("Permission denied")
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.side_effect = os_error

        processor.process_event(InitialFoundEvent(path=path_str))

        configured_mock_fs.exists.assert_called_once_with(path_obj)
        configured_mock_fs.stat.assert_called_once_with(path_obj)
        assert not processor.file_positions
        assert not processor.file_buffers
        mock_safe_put.assert_not_called()
        assert find_log_record(
            caplog,
            logging.WARNING,
            [f"Could not stat file [{path_obj}] on Initial track", str(os_error)],
        )

    def test_created_event_tracks_file(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
    ):
        path_str, path_obj, file_size = (
            "/logs/newly_created.log",
            Path("/logs/newly_created.log"),
            0,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(file_size)

        processor.process_event(CreatedEvent(path=path_str))

        configured_mock_fs.exists.assert_called_once_with(path_obj)
        configured_mock_fs.stat.assert_called_once_with(path_obj)
        assert processor.file_positions == {path_obj: file_size}
        assert processor.file_buffers == {path_obj: b""}
        mock_safe_put.assert_not_called()

    # === Requirement #3: Append Handling & Modified Scenarios ===

    def test_modified_append_success_reads_parses_enqueues(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        mock_move_queue: MagicMock,
    ):
        path_str, path_obj = "/logs/app_append.log", Path("/logs/app_append.log")
        initial_pos, initial_buffer = 100, b"partial "
        new_data_read = b"line one\nline two"
        final_pos_after_read = initial_pos + len(new_data_read)
        current_fs_size = final_pos_after_read
        lines_from_flush, remainder_buffer = ["partial line one"], b"line two"
        target_path_str, target_path_obj = (
            "/processed/line_one.dat",
            Path("/processed/line_one.dat"),
        )
        parsed_line = create_mock_parsed_line(target_path_str)

        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            initial_pos,
            initial_buffer,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(current_fs_size)
        mock_fh = configured_mock_fs.open.return_value.__enter__.return_value
        mock_fh.read.return_value = new_data_read
        mock_fh.tell.return_value = final_pos_after_read
        mock_flush.return_value, mock_parse.return_value = (
            (lines_from_flush, remainder_buffer),
            parsed_line,
        )

        processor.process_event(ModifiedEvent(path=path_str))

        configured_mock_fs.open.assert_called_once_with(path_obj, "rb")
        mock_fh.seek.assert_called_once_with(initial_pos)
        mock_fh.read.assert_called_once_with(current_fs_size - initial_pos)
        mock_flush.assert_called_once_with(initial_buffer + new_data_read)
        mock_parse.assert_called_once_with(lines_from_flush[0])
        mock_safe_put.assert_called_once_with(
            item=target_path_obj,
            output_queue=mock_move_queue,
            queue_name=processor.move_queue_name,
        )
        assert processor.file_positions[path_obj] == final_pos_after_read
        assert processor.file_buffers[path_obj] == remainder_buffer

    def test_modified_no_size_change_does_nothing(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)
        path_str, path_obj = "/logs/no_change.log", Path("/logs/no_change.log")
        initial_pos, initial_buffer = 500, b"abc"
        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            initial_pos,
            initial_buffer,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(initial_pos)

        processor.process_event(ModifiedEvent(path=path_str))

        configured_mock_fs.open.assert_not_called()
        mock_flush.assert_not_called()
        mock_parse.assert_not_called()
        mock_safe_put.assert_not_called()
        assert processor.file_positions[path_obj] == initial_pos
        assert processor.file_buffers[path_obj] == initial_buffer
        assert find_log_record(
            caplog, logging.DEBUG, [f"No change in size for {path_obj}"]
        )

    def test_modified_handles_fs_read_error(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING)
        path_str, path_obj = "/logs/read_error.log", Path("/logs/read_error.log")
        initial_pos, initial_buffer, current_fs_size = 100, b"data", 200
        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            initial_pos,
            initial_buffer,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(current_fs_size)
        read_exception = OSError("Disk read failed!")
        configured_mock_fs.open.return_value.__enter__.return_value.read.side_effect = (
            read_exception
        )

        processor.process_event(ModifiedEvent(path=path_str))

        mock_fh = configured_mock_fs.open.return_value.__enter__.return_value
        mock_fh.tell.assert_not_called()
        mock_flush.assert_not_called()
        mock_parse.assert_not_called()
        mock_safe_put.assert_not_called()
        assert processor.file_positions[path_obj] == initial_pos
        assert processor.file_buffers[path_obj] == initial_buffer
        assert find_log_record(
            caplog,
            logging.WARNING,
            [
                f"Error reading data from {path_obj} at pos {initial_pos}",
                str(read_exception),
            ],
        )

    def test_modified_late_sync_tracks_untracked_file(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        path_str, path_obj, current_fs_size = (
            "/logs/late_sync.log",
            Path("/logs/late_sync.log"),
            150,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(current_fs_size)

        with patch.object(
            processor, "_handle_track", wraps=processor._handle_track
        ) as mock_handle_track:
            processor.process_event(ModifiedEvent(path=path_str))
            mock_handle_track.assert_called_once_with(path_obj, "Late sync")

        assert processor.file_positions[path_obj] == current_fs_size
        assert processor.file_buffers[path_obj] == b""
        assert find_log_record(
            caplog,
            logging.INFO,
            [f"Late sync: untracked file modified, tracking now: {path_obj}"],
        )
        assert find_log_record(
            caplog,
            logging.INFO,
            [f"Late sync at EOF ({current_fs_size} bytes): {path_obj}"],
        )

    def test_modified_file_becomes_non_existent(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING)
        path_str, path_obj = "/logs/disappeared.log", Path("/logs/disappeared.log")
        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            100,
            b"stuff",
        )
        configured_mock_fs.exists.return_value = False

        with patch.object(
            processor, "_handle_deleted", wraps=processor._handle_deleted
        ) as mock_handle_deleted:
            processor.process_event(ModifiedEvent(path=path_str))
            mock_handle_deleted.assert_called_once_with(path_obj)

        assert path_obj not in processor.file_positions
        assert path_obj not in processor.file_buffers
        assert find_log_record(
            caplog,
            logging.WARNING,
            [f"Modified event for non-existent file: {path_obj}", "Treating as delete"],
        )

    # === Requirement #4: Truncation Handling ===
    @pytest.mark.parametrize("new_size", [50, 0])
    def test_modified_truncation_resets_state(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
        new_size: int,
    ):
        caplog.set_level(logging.WARNING)
        path_str = f"/logs/trunc_{new_size}.log"
        path_obj = Path(path_str)
        initial_pos, initial_buffer = 100, b"old data"
        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            initial_pos,
            initial_buffer,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(new_size)

        processor.process_event(ModifiedEvent(path=path_str))

        configured_mock_fs.open.assert_not_called()
        mock_flush.assert_not_called()
        mock_parse.assert_not_called()
        mock_safe_put.assert_not_called()
        assert processor.file_positions == {path_obj: new_size}
        assert processor.file_buffers == {path_obj: b""}
        assert find_log_record(
            caplog,
            logging.WARNING,
            [f"File truncated (new {new_size} < last {initial_pos})", str(path_obj)],
        )

    # === Requirement #2: Deletion Handling ===

    def test_deleted_event_clears_known_file_state(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        path_str, path_obj = "/logs/to_delete.log", Path("/logs/to_delete.log")
        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            100,
            b"some buffer",
        )

        processor.process_event(DeletedEvent(path=path_str))

        assert path_obj not in processor.file_positions
        assert path_obj not in processor.file_buffers
        configured_mock_fs.exists.assert_not_called()
        mock_safe_put.assert_not_called()
        assert find_log_record(
            caplog,
            logging.INFO,
            [
                f"Stopped tracking deleted file {path_obj}",
                "was at pos 100",
                "buffer 11 bytes",
            ],
        )

    def test_deleted_event_for_untracked_file(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)
        path_str, path_obj = (
            "/logs/untracked_delete.log",
            Path("/logs/untracked_delete.log"),
        )

        processor.process_event(DeletedEvent(path=path_str))

        assert not processor.file_positions
        assert not processor.file_buffers
        mock_safe_put.assert_not_called()
        assert find_log_record(
            caplog,
            logging.DEBUG,
            [f"Delete event for untracked or already removed file: {path_obj}"],
        )

    # === Requirement #5: Move Handling ===

    def test_moved_event_deletes_src_tracks_dest(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
    ):
        src_str, dst_str = "/logs/old_name.log", "/logs/new_name.log"
        src_path, dst_path = Path(src_str), Path(dst_str)
        initial_src_pos, dest_fs_size = 200, 50
        processor.file_positions[src_path], processor.file_buffers[src_path] = (
            initial_src_pos,
            b"src buf",
        )

        def exists_side_effect(p):
            return p == dst_path

        def stat_side_effect(p):
            if p == dst_path:
                return create_mock_stat_result(dest_fs_size)
            raise FileNotFoundError

        configured_mock_fs.exists.side_effect = exists_side_effect
        configured_mock_fs.stat.side_effect = stat_side_effect

        processor.process_event(MovedEvent(src_path=src_str, dest_path=dst_str))

        assert src_path not in processor.file_positions
        assert src_path not in processor.file_buffers
        assert processor.file_positions == {dst_path: dest_fs_size}
        assert processor.file_buffers == {dst_path: b""}
        configured_mock_fs.exists.assert_any_call(dst_path)
        configured_mock_fs.stat.assert_called_once_with(dst_path)
        mock_safe_put.assert_not_called()

    # === Error Handling in _process_new_lines (indirectly via ModifiedEvent) ===

    def test_process_new_lines_handles_flush_error(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.ERROR)
        path_str, path_obj = "/logs/flush_error.log", Path("/logs/flush_error.log")
        initial_pos, initial_buffer, new_data_read = 10, b"existing", b" new data"
        current_fs_size = final_pos_after_read = initial_pos + len(new_data_read)
        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            initial_pos,
            initial_buffer,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(current_fs_size)
        mock_fh = configured_mock_fs.open.return_value.__enter__.return_value
        mock_fh.read.return_value, mock_fh.tell.return_value = (
            new_data_read,
            final_pos_after_read,
        )
        flush_exception = ValueError("Flush decoding failed")
        mock_flush.side_effect = flush_exception

        processor.process_event(ModifiedEvent(path=path_str))

        mock_flush.assert_called_once_with(initial_buffer + new_data_read)
        mock_parse.assert_not_called()
        mock_safe_put.assert_not_called()
        assert processor.file_positions[path_obj] == final_pos_after_read
        assert processor.file_buffers[path_obj] == initial_buffer
        assert find_log_record(
            caplog,
            logging.ERROR,
            [f"Error flushing buffer for {path_obj}", str(flush_exception)],
        )

    def test_process_new_lines_handles_parse_error(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.ERROR)
        path_str, path_obj = "/logs/parse_error.log", Path("/logs/parse_error.log")
        initial_pos, initial_buffer, new_data_read = 0, b"", b"bad line\n"
        current_fs_size = final_pos_after_read = len(new_data_read)
        lines_from_flush, remainder_buffer = ["bad line"], b""
        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            initial_pos,
            initial_buffer,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(current_fs_size)
        mock_fh = configured_mock_fs.open.return_value.__enter__.return_value
        mock_fh.read.return_value, mock_fh.tell.return_value = (
            new_data_read,
            final_pos_after_read,
        )
        parse_exception = LineParsingError(
            "Invalid format", "bad line"
        )  # Use real error for realistic msg
        mock_flush.return_value, mock_parse.side_effect = (
            (lines_from_flush, remainder_buffer),
            parse_exception,
        )

        processor.process_event(ModifiedEvent(path=path_str))

        mock_flush.assert_called_once_with(initial_buffer + new_data_read)
        mock_parse.assert_called_once_with(lines_from_flush[0])
        mock_safe_put.assert_not_called()
        assert processor.file_positions[path_obj] == final_pos_after_read
        assert processor.file_buffers[path_obj] == remainder_buffer
        assert find_log_record(
            caplog,
            logging.ERROR,
            [f"Error processing line 'bad line' from {path_obj}", str(parse_exception)],
        )

    def test_process_new_lines_handles_enqueue_error(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,
        mock_move_queue: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.ERROR)
        path_str, path_obj = "/logs/enqueue_error.log", Path("/logs/enqueue_error.log")
        raw_line_content = "123,/target/file.dat,aabbcc"
        new_data_read = raw_line_content.encode("utf-8") + b"\n"
        initial_pos, initial_buffer = 0, b""
        current_fs_size = final_pos_after_read = len(new_data_read)
        lines_from_flush, remainder_buffer = [raw_line_content], b""
        target_path_str, target_path_obj = "/target/file.dat", Path("/target/file.dat")
        parsed_line = create_mock_parsed_line(target_path_str)

        processor.file_positions[path_obj], processor.file_buffers[path_obj] = (
            initial_pos,
            initial_buffer,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(current_fs_size)
        mock_fh = configured_mock_fs.open.return_value.__enter__.return_value
        mock_fh.read.return_value, mock_fh.tell.return_value = (
            new_data_read,
            final_pos_after_read,
        )
        mock_flush.return_value, mock_parse.return_value = (
            (lines_from_flush, remainder_buffer),
            parsed_line,
        )

        enqueue_exception = QueuePutError(
            f"Queue full (queue: {processor.move_queue_name})"
        )
        mock_safe_put.side_effect = enqueue_exception

        processor.process_event(ModifiedEvent(path=path_str))

        mock_flush.assert_called_once_with(initial_buffer + new_data_read)
        mock_parse.assert_called_once_with(lines_from_flush[0])
        mock_safe_put.assert_called_once_with(
            item=target_path_obj,
            output_queue=mock_move_queue,
            queue_name=processor.move_queue_name,
        )
        assert processor.file_positions[path_obj] == final_pos_after_read
        assert processor.file_buffers[path_obj] == remainder_buffer
        assert find_log_record(
            caplog,
            logging.ERROR,
            [
                "QueuePutError enqueuing target",
                f"line '{raw_line_content[:100]}'",
                str(path_obj),
                str(enqueue_exception),
            ],
        )

    # === Test Custom Enqueuer and Unhandled Event ===
    def test_processor_uses_custom_enqueuer_if_provided(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor_with_custom_enqueuer,
        configured_mock_fs: MagicMock,
    ):
        proc, mock_custom_enqueuer = processor_with_custom_enqueuer
        path_str, path_obj = (
            "/logs/custom_enqueue.log",
            Path("/logs/custom_enqueue.log"),
        )
        raw_line_content = "1,/custom/target.dat,hash"
        new_data_read = raw_line_content.encode("utf-8") + b"\n"
        initial_pos, initial_buffer = 0, b""
        current_fs_size = final_pos_after_read = len(new_data_read)
        lines_from_flush, remainder_buffer = [raw_line_content], b""
        target_path_str, target_path_obj = (
            "/custom/target.dat",
            Path("/custom/target.dat"),
        )
        parsed_line = create_mock_parsed_line(target_path_str)

        proc.file_positions[path_obj], proc.file_buffers[path_obj] = (
            initial_pos,
            initial_buffer,
        )
        configured_mock_fs.exists.return_value = True
        configured_mock_fs.stat.return_value = create_mock_stat_result(current_fs_size)
        mock_fh = configured_mock_fs.open.return_value.__enter__.return_value
        mock_fh.read.return_value, mock_fh.tell.return_value = (
            new_data_read,
            final_pos_after_read,
        )
        mock_flush.return_value, mock_parse.return_value = (
            (lines_from_flush, remainder_buffer),
            parsed_line,
        )

        proc.process_event(ModifiedEvent(path=path_str))

        mock_custom_enqueuer.assert_called_once_with(target_path_obj)
        mock_safe_put.assert_not_called()

    @pytest.mark.parametrize(
        "unhandled_event_instance",
        [
            MagicMock(spec=TailerQueueEvent, name="MockTailerEvent"),
            object(),  # A completely unrelated object
        ],
    )
    def test_process_event_handles_unknown_event_type(
        self,
        mock_parse,
        mock_flush,
        mock_safe_put,
        processor: TailProcessor,
        configured_mock_fs: MagicMock,  # Use configured_mock_fs here
        caplog: pytest.LogCaptureFixture,
        unhandled_event_instance,
    ):
        caplog.set_level(logging.WARNING)
        processor.process_event(unhandled_event_instance)

        configured_mock_fs.exists.assert_not_called()
        configured_mock_fs.stat.assert_not_called()
        configured_mock_fs.open.assert_not_called()
        mock_safe_put.assert_not_called()
        mock_parse.assert_not_called()
        mock_flush.assert_not_called()
        assert not processor.file_positions
        assert not processor.file_buffers
        assert find_log_record(
            caplog,
            logging.WARNING,
            [f"Unhandled event type: {type(unhandled_event_instance)}"],
        )
