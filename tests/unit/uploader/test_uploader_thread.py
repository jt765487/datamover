import logging
import threading
import time
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

from datamover.file_functions.fs_mock import FS
from datamover.protocols import FileScanner
from datamover.uploader.send_file_with_retries import RetryableFileSender

# Class under test
from datamover.uploader.uploader_thread import UploaderThread

# Log assertion helper
from tests.test_utils.logging_helpers import find_log_record


# --- Test Fixtures and Helpers ---


class MockFileEntry:
    """Simple mock for os.DirEntry like objects used by the scanner."""

    def __init__(self, path: Path):
        self.path: Path = path
        self.name: str = Path(path).name

    def __repr__(self):
        return f"MockFileEntry(path='{self.path}')"

    def __eq__(self, other):
        if isinstance(other, MockFileEntry):
            return self.path == other.path
        return False


# Test constants
TEST_POLL_INTERVAL = 0.01
THREAD_JOIN_TIMEOUT = 0.5
TEST_HEARTBEAT_INTERVAL = 0.03  # Default for factory, can be overridden
TEST_FILE_EXTENSION = "pcap"  # Default for factory


def run_thread_for_duration(
    thread: UploaderThread,
    duration: float,
    join_timeout: float = THREAD_JOIN_TIMEOUT,
):
    """Starts a thread, lets it run for a duration, then stops and joins it."""
    thread.start()
    time.sleep(duration)
    if not thread.stop_event.is_set():
        thread.stop_event.set()
    thread.join(timeout=join_timeout)
    assert not thread.is_alive(), f"Thread {thread.name} did not stop as expected."


@pytest.fixture
def mock_file_scanner() -> MagicMock:
    """Provides a mock FileScanner."""
    return MagicMock(spec=FileScanner)


@pytest.fixture
def mock_file_sender() -> MagicMock:
    """Provides a mock RetryableFileSender."""
    return MagicMock(spec=RetryableFileSender)


@pytest.fixture
def mock_fs_for_uploader() -> MagicMock:
    """Provides a mock FS abstraction."""
    return MagicMock(spec=FS)


@pytest.fixture
def validated_work_dir(tmp_path: Path) -> Path:
    """Creates a temporary directory for the uploader to watch."""
    work_dir = tmp_path / "uploader_work_dir_v4"  # Incremented version for safety
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


@pytest.fixture
def uploader_thread_factory(
    validated_work_dir: Path,
    mock_file_scanner: MagicMock,
    mock_file_sender: MagicMock,
    mock_fs_for_uploader: MagicMock,
):
    """Factory fixture to create UploaderThread instances with teardown."""
    created_threads: List[UploaderThread] = []

    def _factory(
        thread_name: str = "TestUploader",
        file_ext: str = TEST_FILE_EXTENSION,
        poll_interval: float = TEST_POLL_INTERVAL,
        heartbeat_interval: float = TEST_HEARTBEAT_INTERVAL,
        custom_scanner: Optional[MagicMock] = None,
        custom_sender: Optional[MagicMock] = None,
        custom_fs: Optional[MagicMock] = None,
        custom_stop_event: Optional[threading.Event] = None,
    ) -> UploaderThread:
        """Creates and tracks an UploaderThread instance."""
        eff_stop_event = (
            custom_stop_event if custom_stop_event is not None else threading.Event()
        )

        thread = UploaderThread(
            thread_name=thread_name,
            validated_work_dir=validated_work_dir,
            file_extension_no_dot=file_ext,
            stop_event=eff_stop_event,
            poll_interval=poll_interval,
            heartbeat_interval=heartbeat_interval,
            file_scanner=custom_scanner or mock_file_scanner,
            file_sender=custom_sender or mock_file_sender,
            fs=custom_fs or mock_fs_for_uploader,
        )
        # Store the event used for potential teardown access
        thread._factory_managed_stop_event = eff_stop_event
        created_threads.append(thread)
        return thread

    yield _factory

    # Teardown: Ensure all created threads are stopped
    for t in created_threads:
        if t.is_alive():
            # Use the specific event the thread was created with
            thread_stop_event_to_set = getattr(
                t,
                "_factory_managed_stop_event",
                t.stop_event,  # Fallback just in case
            )
            if not thread_stop_event_to_set.is_set():
                thread_stop_event_to_set.set()
            t.join(timeout=THREAD_JOIN_TIMEOUT)


# --- Test Classes ---


class TestUploaderThreadInitialization:
    """Tests the __init__ method of UploaderThread."""

    def test_initialization_stores_args_and_calculates_heartbeat(
        self,
        uploader_thread_factory,
        validated_work_dir: Path,
        mock_file_scanner: MagicMock,
        mock_file_sender: MagicMock,
        mock_fs_for_uploader: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify constructor sets attributes correctly and logs initialization."""
        caplog.set_level(logging.DEBUG)
        name = "MyUploaderInitTest"
        ext = "dat"
        poll = 0.05
        heartbeat_input = 0.15

        test_specific_stop_event = threading.Event()

        thread = uploader_thread_factory(
            thread_name=name,
            file_ext=ext,
            poll_interval=poll,
            heartbeat_interval=heartbeat_input,
            custom_stop_event=test_specific_stop_event,
        )

        assert thread.name == name
        assert thread.daemon is True
        assert thread.validated_work_dir == validated_work_dir
        assert thread.file_extension_no_dot == ext
        assert thread.stop_event is test_specific_stop_event
        assert thread.poll_interval == poll
        assert thread.file_scanner is mock_file_scanner
        assert thread.file_sender is mock_file_sender
        assert thread.fs is mock_fs_for_uploader
        assert thread.critically_failed_files == set()
        assert thread.empty_scan_streak == 0  # Check new attribute
        assert thread.current_cycle_count == 0
        assert thread.scan_cycles_completed == 0
        assert thread.files_processed_count == 0

        assert thread.heartbeat_target_interval_s == heartbeat_input
        expected_cycles_for_heartbeat = max(1, int(round(heartbeat_input / poll)))
        assert thread.cycles_for_heartbeat == expected_cycles_for_heartbeat

        # --- Corrected Log Assertion ---
        # Match the exact format string from UploaderThread.__init__
        init_log_msg = (
            f"{name} initialized. Watching {validated_work_dir} "
            f"for *.{ext}. Heartbeat every {expected_cycles_for_heartbeat} "
            f"cycles (~{heartbeat_input} s)."
        )
        assert find_log_record(caplog, logging.DEBUG, [init_log_msg]) is not None, (
            f"Initialization log message not found or incorrect. Expected: '{init_log_msg}'"
        )


class TestUploaderThreadRunLogic:
    """Tests the run() method logic of UploaderThread."""

    def test_starts_logs_and_stops_cleanly_on_stop_event(
        self, uploader_thread_factory, caplog: pytest.LogCaptureFixture
    ):
        """Verify start and stop logs are emitted and thread terminates."""
        caplog.set_level(logging.INFO)
        thread_name = "CleanStopUploaderTest"
        thread = uploader_thread_factory(
            thread_name=thread_name, poll_interval=0.02, heartbeat_interval=1.0
        )

        run_thread_for_duration(thread, duration=thread.poll_interval * 2.5)

        assert (
            find_log_record(caplog, logging.INFO, [f"{thread_name} starting run loop."])
            is not None
        ), "Start log not found."
        # Check for potential stop messages (either from wait or normal exit)
        stop_log_wait = find_log_record(
            caplog,
            logging.INFO,
            [f"{thread_name} received stop signal during wait; exiting."],
        )
        stop_log_normal = find_log_record(
            caplog, logging.INFO, [f"{thread_name} stopping run loop."]
        )
        assert stop_log_wait is not None or stop_log_normal is not None, (
            "Expected stop log message not found."
        )
        # The normal 'stopping run loop' message should always appear at the end
        assert stop_log_normal is not None, "Final 'stopping run loop' log not found."

    def test_scans_and_sends_found_files_successfully(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        mock_file_sender: MagicMock,
        validated_work_dir: Path,
        mock_fs_for_uploader: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify files found by scanner are passed to sender and logged."""
        caplog.set_level(logging.DEBUG)
        thread_name = "SuccessfulSendTest"
        thread = uploader_thread_factory(
            thread_name=thread_name, file_ext=TEST_FILE_EXTENSION
        )

        file_path1 = validated_work_dir / f"file1.{TEST_FILE_EXTENSION}"
        file_path2 = validated_work_dir / f"file2.{TEST_FILE_EXTENSION}"
        mock_file_scanner.return_value = [
            MockFileEntry(path=file_path1),
            MockFileEntry(path=file_path2),
        ]
        mock_file_sender.send_file.return_value = True

        run_thread_for_duration(thread, duration=thread.poll_interval * 3.5)

        # Scanner call check
        mock_file_scanner.assert_called_with(
            directory=validated_work_dir,
            fs=mock_fs_for_uploader,
            extension_no_dot=TEST_FILE_EXTENSION,
        )
        assert mock_file_scanner.call_count > 0

        # Sender call check (allow for potential multiple calls due to timing)
        send_calls = [
            call.args[0] for call in mock_file_sender.send_file.call_args_list
        ]
        assert file_path1 in send_calls
        assert file_path2 in send_calls

        # --- Corrected Log Assertion ---
        # Check the log message generated *before* calling send_file
        assert (
            find_log_record(
                caplog, logging.DEBUG, [f"{thread_name} sending file: {file_path1}"]
            )
            is not None
        ), f"Send log for {file_path1} not found."
        assert (
            find_log_record(
                caplog, logging.DEBUG, [f"{thread_name} sending file: {file_path2}"]
            )
            is not None
        ), f"Send log for {file_path2} not found."

        assert not thread.critically_failed_files
        assert thread.files_processed_count >= 2  # Should have processed both

    def test_handles_file_sender_returns_false(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        mock_file_sender: MagicMock,
        validated_work_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify critical failure log when sender returns False."""
        caplog.set_level(logging.ERROR)
        thread_name = "SenderFalseTest"
        thread = uploader_thread_factory(thread_name=thread_name)
        file_path = validated_work_dir / "fail_send.pcap"
        mock_file_scanner.return_value = [MockFileEntry(path=file_path)]
        mock_file_sender.send_file.return_value = False  # Simulate critical failure

        run_thread_for_duration(thread, duration=thread.poll_interval * 3.5)

        mock_file_sender.send_file.assert_called_with(file_path)
        assert file_path in thread.critically_failed_files

        # --- Corrected Log Assertion ---
        # Match the exact error message from UploaderThread.run
        expected_log = (
            f"{thread_name} critical failure for file {file_path} "
            f"(sender returned False)."
        )
        assert find_log_record(caplog, logging.ERROR, [expected_log]) is not None, (
            f"Critical failure log not found or incorrect. Expected: '{expected_log}'"
        )

    def test_handles_file_sender_raises_exception(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        mock_file_sender: MagicMock,  # Ensure this is present
        validated_work_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify critical failure log when sender raises an exception."""
        caplog.set_level(logging.ERROR)  # logger.exception logs at ERROR level
        thread_name = "SenderExceptionTest"
        thread = uploader_thread_factory(thread_name=thread_name)
        file_path = validated_work_dir / "exc_send.pcap"
        send_exception = RuntimeError("Unhandled send error")
        mock_file_scanner.return_value = [MockFileEntry(path=file_path)]
        mock_file_sender.send_file.side_effect = send_exception

        run_thread_for_duration(thread, duration=thread.poll_interval * 3.5)

        mock_file_sender.send_file.assert_called_with(file_path)
        assert file_path in thread.critically_failed_files

        # --- Corrected Log Assertion ---
        expected_log_prefix = (
            f"{thread_name} CRITICAL: exception during send_file('{file_path}')."
        )
        # --- REMOVED partial_match=True ---
        log_rec = find_log_record(caplog, logging.ERROR, [expected_log_prefix])

        assert log_rec is not None, (
            f"Critical exception log not found or incorrect. Expected prefix: '{expected_log_prefix}'"
        )
        # Verify exception info is attached by logger.exception
        assert log_rec.exc_info is not None, "Log record missing exception info."
        assert log_rec.exc_info[0] is type(send_exception), (
            "Incorrect exception type logged."
        )

    def test_skips_critically_failed_files_on_subsequent_scan(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        mock_file_sender: MagicMock,
        validated_work_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify already failed files are skipped and not resent."""
        caplog.set_level(logging.DEBUG)  # Need DEBUG to see the skipping log
        thread_name = "SkipFailedTest"
        thread = uploader_thread_factory(thread_name=thread_name, poll_interval=0.005)
        file_path = validated_work_dir / "critical.pcap"

        # Simulate scanner returning the file multiple times
        mock_file_scanner.side_effect = [
            [MockFileEntry(path=file_path)],  # First scan, sender will fail it
            [MockFileEntry(path=file_path)],  # Second scan, should be skipped
            [MockFileEntry(path=file_path)],  # Third scan, should be skipped
            [],  # Subsequent scans find nothing
            [],
        ]
        # Simulate the first send failing critically
        mock_file_sender.send_file.return_value = False

        run_thread_for_duration(
            thread,
            duration=thread.poll_interval * 10,  # Run for several cycles
        )

        assert file_path in thread.critically_failed_files
        # send_file should only be called ONCE for this path
        mock_file_sender.send_file.assert_called_once_with(file_path)

        # Verify the skipping log message appeared at least once
        skip_log_msg = f"{thread_name} skipping critically failed file: {file_path}"
        assert find_log_record(caplog, logging.DEBUG, [skip_log_msg]) is not None, (
            f"Log message for skipping failed file not found. Expected: '{skip_log_msg}'"
        )

    def test_handles_file_scanner_exception(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        mock_file_sender: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify thread survives and logs error if file_scanner fails."""
        caplog.set_level(logging.ERROR)  # logger.exception logs at ERROR
        thread_name = "ScannerExceptionTest"
        thread = uploader_thread_factory(thread_name=thread_name)
        scan_exception = IOError("Scanner disk read failure")
        mock_file_scanner.side_effect = scan_exception

        run_thread_for_duration(thread, duration=thread.poll_interval * 3.5)

        mock_file_sender.send_file.assert_not_called()  # Sender shouldn't be reached

        # --- Corrected Log Assertion ---
        expected_log_prefix = f"{thread_name} unexpected error in scan/process loop."
        # --- REMOVED partial_match=True ---
        log_rec = find_log_record(caplog, logging.ERROR, [expected_log_prefix])

        assert log_rec is not None, (
            f"Scanner exception log not found. Expected prefix: '{expected_log_prefix}'"
        )
        # Verify exception info is attached
        assert log_rec.exc_info is not None, "Log record missing exception info."
        assert log_rec.exc_info[0] is type(scan_exception), (
            "Incorrect exception type logged."
        )

    def test_heartbeat_log_emitted_periodically(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        validated_work_dir: Path,  # Needed for the log message
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify heartbeat INFO message appears at the configured interval."""
        caplog.set_level(logging.INFO)  # Heartbeat is INFO level
        thread_name = "HeartbeatLoggerTest"
        test_poll_interval = 0.01
        test_heartbeat_interval = 0.025  # Expect heartbeat every 2 or 3 cycles

        thread = uploader_thread_factory(
            thread_name=thread_name,
            poll_interval=test_poll_interval,
            heartbeat_interval=test_heartbeat_interval,
        )
        mock_file_scanner.return_value = []  # No files to process

        # cycles_for_heartbeat = max(1, int(round(0.025 / 0.01))) = max(1, 2) = 2
        assert thread.cycles_for_heartbeat == 2

        # Run for enough cycles to get at least two heartbeats (e.g., 2*2 + buffer)
        run_duration = (test_poll_interval * thread.cycles_for_heartbeat * 2) + (
            test_poll_interval
            * 1.5  # 0.01 * 2 * 2 + 0.01 * 1.5 = 0.04 + 0.015 = 0.055s
        )
        run_thread_for_duration(thread, duration=run_duration)

        # --- Corrected Log Assertion ---
        # Match the actual heartbeat log message format
        expected_heartbeat_msg = (
            f"{thread_name} heartbeat: watching directory {validated_work_dir}"
        )
        heartbeat_logs = [
            r
            for r in caplog.records
            if r.message == expected_heartbeat_msg and r.levelno == logging.INFO
        ]

        # Depending on exact timing, could be 2 or 3 if it just crosses boundary
        assert len(heartbeat_logs) >= 2, (
            f"Expected at least 2 heartbeat logs for duration {run_duration}s "
            f"with poll {test_poll_interval}s and heartbeat {test_heartbeat_interval}s "
            f"(cycles_for_heartbeat={thread.cycles_for_heartbeat}). "
            f"Got {len(heartbeat_logs)} logs: {[r.message for r in heartbeat_logs]}"
        )

    def test_stop_event_during_file_processing_loop(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        mock_file_sender: MagicMock,
        validated_work_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify thread stops promptly if event set while processing multiple files."""
        caplog.set_level(logging.INFO)  # Need INFO for the stop log
        thread_name = "StopDuringFileProcessingTest"
        thread_specific_stop_event = threading.Event()
        thread = uploader_thread_factory(
            thread_name=thread_name, custom_stop_event=thread_specific_stop_event
        )

        file_path1 = validated_work_dir / f"fileA.{TEST_FILE_EXTENSION}"
        file_path2 = validated_work_dir / f"fileB.{TEST_FILE_EXTENSION}"
        file_path3 = validated_work_dir / f"fileC.{TEST_FILE_EXTENSION}"

        # Scanner returns multiple files in one go
        mock_file_scanner.return_value = [
            MockFileEntry(path=file_path1),
            MockFileEntry(path=file_path2),
            MockFileEntry(path=file_path3),
        ]

        processed_files_tracker: List[Path] = []

        # Side effect to set stop event *after* processing the first file
        def send_file_side_effect(path_arg: Path) -> bool:
            processed_files_tracker.append(path_arg)
            # Set stop *after* processing file1 is complete (conceptually)
            if path_arg == file_path1:
                thread_specific_stop_event.set()
            # Add a tiny delay to allow the main loop to potentially check the event
            time.sleep(0.001)
            return True

        mock_file_sender.send_file.side_effect = send_file_side_effect

        thread.start()
        # Wait long enough for potential processing + stop detection
        thread.join(timeout=THREAD_JOIN_TIMEOUT * 2)
        assert not thread.is_alive(), f"{thread_name} did not stop as expected."

        # Assertions on processed files
        assert file_path1 in processed_files_tracker, (
            "file_path1 should have been processed"
        )
        # Stop event is checked *before* processing the next file in the loop
        assert file_path2 not in processed_files_tracker, (
            f"File {file_path2.name} was processed after stop event. Processed: {processed_files_tracker}"
        )
        assert file_path3 not in processed_files_tracker, (
            f"File {file_path3.name} was processed after stop event. Processed: {processed_files_tracker}"
        )
        assert len(processed_files_tracker) == 1, (
            f"Expected only file1 to be processed. Processed: {processed_files_tracker}"
        )

        # --- Corrected Log Assertion ---
        # Check for the log message indicating the break from the file loop
        expected_stop_log = f"{thread_name} stop event detected; breaking file loop."
        assert find_log_record(caplog, logging.INFO, [expected_stop_log]) is not None, (
            f"Log for stop during processing loop not found. Expected: '{expected_stop_log}'"
        )

    # --- Potential New Tests for Empty Scan Streak Logging ---

    def test_empty_scan_streak_logging_initial_and_periodic(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify empty scan log appears on first empty scan and periodically after."""
        caplog.set_level(logging.DEBUG)  # Empty scan logs are DEBUG
        thread_name = "EmptyStreakTest"
        poll_interval = 0.01
        # Set heartbeat interval so heartbeat cycle != 1 (e.g., 3 cycles)
        heartbeat_interval = poll_interval * 2.5  # cycles = max(1, round(2.5)) = 2
        thread = uploader_thread_factory(
            thread_name=thread_name,
            poll_interval=poll_interval,
            heartbeat_interval=heartbeat_interval,
        )
        mock_file_scanner.return_value = []  # Always return no files

        # Run long enough for first empty log + at least one periodic one
        # e.g., 1st log cycle 1, periodic at cycle 2 (since cycles_for_hb=2)
        run_duration = poll_interval * (
            thread.cycles_for_heartbeat + 1.5
        )  # Run ~3 cycles
        run_thread_for_duration(thread, duration=run_duration)

        # Check for the first empty scan log (streak = 1)
        first_empty_log = f"{thread_name}: no files found for 1 consecutive cycle(s)."
        assert find_log_record(caplog, logging.DEBUG, [first_empty_log]), (
            f"Expected first empty scan log not found: '{first_empty_log}'"
        )

        # Check for a periodic empty scan log (streak = cycles_for_heartbeat)
        periodic_empty_log = f"{thread_name}: no files found for {thread.cycles_for_heartbeat} consecutive cycle(s)."
        assert find_log_record(caplog, logging.DEBUG, [periodic_empty_log]), (
            f"Expected periodic empty scan log not found: '{periodic_empty_log}'"
        )

        # Check that intermediate empty scans (e.g., streak=2 if hb=3) are NOT logged excessively
        intermediate_streak = thread.cycles_for_heartbeat - 1
        if intermediate_streak > 1:  # Only relevant if heartbeat cycles > 2
            intermediate_log = f"{thread_name}: no files found for {intermediate_streak} consecutive cycle(s)."
            assert not find_log_record(caplog, logging.DEBUG, [intermediate_log]), (
                f"Unexpected intermediate empty scan log found: '{intermediate_log}'"
            )

    def test_empty_scan_streak_resets_and_logs_recovery(
        self,
        uploader_thread_factory,
        mock_file_scanner: MagicMock,
        mock_file_sender: MagicMock,  # <-- ADDED MISSING FIXTURE
        validated_work_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Verify empty streak resets and recovery is logged when files appear."""
        caplog.set_level(logging.DEBUG)  # Need DEBUG for streak and recovery logs
        thread_name = "StreakResetTest"
        poll_interval = 0.01
        heartbeat_interval = poll_interval * 3.5  # cycles = 4
        thread = uploader_thread_factory(
            thread_name=thread_name,
            poll_interval=poll_interval,
            heartbeat_interval=heartbeat_interval,
        )

        file_path = validated_work_dir / f"found_file.{TEST_FILE_EXTENSION}"

        # Simulate: empty, empty, empty, FOUND, empty
        mock_file_scanner.side_effect = [
            [],  # cycle 1 -> log streak 1
            [],  # cycle 2 -> no log
            [],  # cycle 3 -> no log
            [MockFileEntry(path=file_path)],  # cycle 4 -> log recovery, reset streak
            [],  # cycle 5 -> log streak 1 again
            [],  # cycle 6 -> no log
        ]
        # Make sender succeed (Now mock_file_sender refers to the MagicMock)
        mock_file_sender.send_file.return_value = True

        # Run for ~6 cycles
        run_duration = poll_interval * 6.5
        run_thread_for_duration(thread, duration=run_duration)

        # Check initial empty streak log
        first_empty_log = f"{thread_name}: no files found for 1 consecutive cycle(s)."
        assert find_log_record(caplog, logging.DEBUG, [first_empty_log]), (
            f"Expected first empty scan log not found: '{first_empty_log}'"
        )

        # Streak should have reached at least 3 before reset
        # Determine the streak value *before* it was reset (last scan was empty)
        # Get the actual final streak count from the thread state
        final_streak = thread.empty_scan_streak
        assert final_streak > 0, "Expected final empty_scan_streak > 0"

        # Check for the recovery log message
        # Find the log record to get the logged streak count
        recovery_log_prefix = f"{thread_name}: files detected after "
        recovery_rec = find_log_record(caplog, logging.DEBUG, [recovery_log_prefix])
        assert recovery_rec is not None, (
            f"Expected recovery log not found (prefix: '{recovery_log_prefix}')"
        )

        # Check that the streak reset and the streak=1 log appeared *again* after the file was found
        second_empty_log_records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and first_empty_log in r.message
        ]
        # We expect the streak=1 log to appear twice: once at the beginning, once after recovery
        assert len(second_empty_log_records) >= 2, (
            f"Expected empty streak log (streak=1) to appear again after recovery. Found {len(second_empty_log_records)} times."
        )
