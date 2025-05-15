import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from datamover.scanner.scan_thread import ScanThread
from datamover.scanner.do_single_cycle import DoSingleCycle
from datamover.scanner.file_state_record import FileStateRecord  # For type hinting
from datamover.file_functions.file_exceptions import ScanDirectoryError
from datamover.protocols import (
    SleepCallable,
)

# Assuming find_log_record is in this path, adjust if necessary
from tests.test_utils.logging_helpers import find_log_record

MODULE_LOGGER = "datamover.scanner.scan_thread"  # Logger for ScanThread class
THREAD_NAME = "TestScanner"
SCAN_INTERVAL = 0.1  # seconds
SCAN_DIR = Path("/monitored/test_dir")
LOST_TIMEOUT = 20.0
STUCK_TIMEOUT = 30.0
MOCK_MONO_START = 1000.0
MOCK_MONO_CYCLE_DURATION = 0.02


# --- Module-level Helper Functions for Mock Setup ---


def setup_stop_event_for_cycles(stop_event_mock: MagicMock, num_cycles: int):
    """Helper to configure stop_event.is_set to run for num_cycles then stop."""
    # For N cycles, is_set is checked at start of while loop (N times)
    # and before stop_event.wait (N times)
    side_effects = [False] * (num_cycles * 2) + [
        True
    ]  # True at the end to stop the loop
    stop_event_mock.is_set.side_effect = side_effects


def setup_monotonic_time_for_cycles(
    monotonic_mock: MagicMock,
    num_cycles: int,
    cycle_duration: float = MOCK_MONO_CYCLE_DURATION,
):
    """Helper to configure monotonic_func for num_cycles."""
    times = []
    current_time = MOCK_MONO_START
    for _ in range(num_cycles):
        times.append(current_time)  # Start of cycle
        current_time += cycle_duration
        times.append(current_time)  # End of cycle
    monotonic_mock.side_effect = times
    return times


# --- Fixtures ---


@pytest.fixture
def mock_processor(mocker) -> MagicMock:
    """Mocks the DoSingleCycle processor."""
    proc = MagicMock(spec=DoSingleCycle)
    # Define attributes that ScanThread's __init__ will try to getattr for logging
    proc.directory_to_scan = SCAN_DIR
    proc.lost_timeout = LOST_TIMEOUT
    proc.stuck_active_file_timeout = STUCK_TIMEOUT
    proc.lost_queue_name = "MockLostQ"
    # Default return for process_one_cycle: (next_states, current_lost, current_stuck)
    proc.process_one_cycle.return_value = ({}, set(), set())
    return proc


@pytest.fixture
def mock_stop_event() -> MagicMock:
    """Mocks threading.Event, defaulting to not set, wait not interrupted."""
    evt = MagicMock(spec=threading.Event)
    evt.is_set.return_value = False  # Default: thread runs
    evt.wait.return_value = False  # Default: wait completes normally (not interrupted)
    return evt


@pytest.fixture
def mock_sleep_func() -> MagicMock:
    """Mocks the sleep function (passed to ScanThread but not directly used by it)."""
    return MagicMock(spec=SleepCallable)


@pytest.fixture
def mock_monotonic_func() -> MagicMock:
    """Mocks the monotonic time function."""
    return MagicMock(return_value=MOCK_MONO_START)


@pytest.fixture
def scan_thread_instance(
    mock_processor: MagicMock,
    mock_stop_event: MagicMock,
    mock_sleep_func: MagicMock,
    mock_monotonic_func: MagicMock,
) -> ScanThread:
    """Creates an instance of ScanThread with mocked dependencies."""
    # This instance will be created with the default SCAN_INTERVAL.
    # Tests that need a different interval will modify it directly.
    return ScanThread(
        processor=mock_processor,
        stop_event=mock_stop_event,
        scan_interval_seconds=SCAN_INTERVAL,  # Default interval
        sleep_func=mock_sleep_func,
        monotonic_func=mock_monotonic_func,
        name=THREAD_NAME,
    )


class TestScanThreadInit:
    def test_initialization_stores_attributes_and_logs(
        self,
        mock_processor: MagicMock,
        mock_stop_event: MagicMock,
        mock_sleep_func: MagicMock,
        mock_monotonic_func: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Tests correct attribute initialization and INFO log on creation."""
        caplog.set_level(logging.INFO, logger=MODULE_LOGGER)

        thread = ScanThread(
            processor=mock_processor,
            stop_event=mock_stop_event,
            scan_interval_seconds=SCAN_INTERVAL,
            sleep_func=mock_sleep_func,
            monotonic_func=mock_monotonic_func,
            name=THREAD_NAME,
        )
        assert thread.processor is mock_processor
        assert thread.stop_event is mock_stop_event
        assert thread.scan_interval_seconds == SCAN_INTERVAL
        assert thread.sleep_func is mock_sleep_func
        assert thread.monotonic_func is mock_monotonic_func
        assert thread.name == THREAD_NAME
        assert thread.daemon is True

        log_entry = find_log_record(
            caplog,
            logging.INFO,
            [
                f"Initialized {THREAD_NAME} for '{SCAN_DIR}'",
                f"Interval: {SCAN_INTERVAL:.1f}s",
                f"Lost Timeout: {LOST_TIMEOUT:.1f}",
                f"Stuck Active Timeout: {STUCK_TIMEOUT:.1f}",
                "Lost File Queue: MockLostQ",
            ],
        )
        assert log_entry is not None, "Initialization INFO log not found or incorrect."


class TestScanThreadRun:
    # Happy Path and State Propagation
    def test_run_immediate_stop_before_any_cycle(
        self,
        scan_thread_instance: ScanThread,
        mock_processor: MagicMock,
        mock_stop_event: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Tests the thread exits cleanly if stop_event is set before the first cycle."""
        caplog.set_level(logging.INFO, logger=MODULE_LOGGER)
        mock_stop_event.is_set.return_value = True

        scan_thread_instance.run()

        mock_processor.process_one_cycle.assert_not_called()
        assert (
            find_log_record(
                caplog,
                logging.INFO,
                [f"Starting {THREAD_NAME} monitoring", str(SCAN_DIR)],
            )
            is not None
        )
        assert (
            find_log_record(
                caplog,
                logging.INFO,
                [
                    f"Stopping {THREAD_NAME} monitoring",
                    "Graceful exit after 0 iterations",
                ],
            )
            is not None
        )
        mock_stop_event.wait.assert_not_called()

    def test_run_single_successful_cycle_updates_state_and_logs(
        self,
        scan_thread_instance: ScanThread,
        mock_processor: MagicMock,
        mock_stop_event: MagicMock,
        mock_monotonic_func: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Tests a single successful scan cycle: state update, logging, and wait logic."""
        caplog.set_level(logging.DEBUG, logger=MODULE_LOGGER)
        setup_stop_event_for_cycles(mock_stop_event, num_cycles=1)
        setup_monotonic_time_for_cycles(mock_monotonic_func, num_cycles=1)

        p_next_file = SCAN_DIR / "next_file.dat"
        p_lost_file = SCAN_DIR / "lost_file.dat"
        p_stuck_file = SCAN_DIR / "stuck_file.dat"

        first_cycle_next_states: dict[Path, FileStateRecord] = {
            p_next_file: MagicMock(spec=FileStateRecord)
        }
        first_cycle_lost: set[Path] = {p_lost_file}
        first_cycle_stuck: set[Path] = {p_stuck_file}

        mock_processor.process_one_cycle.return_value = (
            first_cycle_next_states,
            first_cycle_lost,
            first_cycle_stuck,
        )

        scan_thread_instance.run()

        mock_processor.process_one_cycle.assert_called_once_with(
            current_file_states={},
            previously_lost_paths=set(),
            previously_stuck_active_paths=set(),
        )

        assert scan_thread_instance._current_file_states == first_cycle_next_states
        assert scan_thread_instance._previously_lost_paths == first_cycle_lost
        assert scan_thread_instance._previously_stuck_active_paths == first_cycle_stuck

        assert (
            find_log_record(caplog, logging.INFO, [f"Starting {THREAD_NAME}"])
            is not None
        )
        assert (
            find_log_record(caplog, logging.DEBUG, [f"{THREAD_NAME} cycle 1 starting"])
            is not None
        )

        crit_log = find_log_record(
            caplog,
            logging.CRITICAL,
            [
                "NEWLY STUCK ACTIVE files",
                str(SCAN_DIR),
                f"{STUCK_TIMEOUT:.1f} sec",
                str(p_stuck_file.as_posix()),
            ],
        )
        assert crit_log is not None, (
            "CRITICAL log for stuck files not found or incorrect."
        )

        assert (
            find_log_record(
                caplog, logging.DEBUG, [f"{THREAD_NAME} internal state updated"]
            )
            is not None
        )

        numerical_expected_wait_time = SCAN_INTERVAL - MOCK_MONO_CYCLE_DURATION
        assert (
            find_log_record(
                caplog,
                logging.DEBUG,
                [
                    f"{THREAD_NAME} cycle 1 for",
                    "finished",
                    f"(took {MOCK_MONO_CYCLE_DURATION:.3f} sec, success: True)",
                ],
            )
            is not None
        )
        assert (
            find_log_record(
                caplog,
                logging.DEBUG,
                [f"{THREAD_NAME} waiting {numerical_expected_wait_time:.3f} seconds"],
            )
            is not None
        )

        mock_stop_event.wait.assert_called_once_with(
            pytest.approx(numerical_expected_wait_time)
        )

        assert find_log_record(
            caplog,
            logging.INFO,
            [f"Stopping {THREAD_NAME} monitoring", "Graceful exit after 1 iterations"],
        )

    def test_run_two_successful_cycles_propagates_state(
        self,
        scan_thread_instance: ScanThread,
        mock_processor: MagicMock,
        mock_stop_event: MagicMock,
        mock_monotonic_func: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Tests that state from cycle 1 is correctly passed to cycle 2."""
        caplog.set_level(logging.DEBUG, logger=MODULE_LOGGER)
        setup_stop_event_for_cycles(mock_stop_event, num_cycles=2)
        setup_monotonic_time_for_cycles(
            mock_monotonic_func, num_cycles=2, cycle_duration=0.01
        )

        p_c1_next = SCAN_DIR / "c1_next.dat"
        c1_next_states = {p_c1_next: MagicMock(spec=FileStateRecord, name="C1_Next")}
        p_c1_lost = SCAN_DIR / "c1_lost.dat"
        c1_lost_set = {p_c1_lost}
        p_c1_stuck = SCAN_DIR / "c1_stuck.dat"
        c1_stuck_set = {p_c1_stuck}

        p_c2_next = SCAN_DIR / "c2_next.dat"
        c2_next_states = {p_c2_next: MagicMock(spec=FileStateRecord, name="C2_Next")}
        c2_lost_set = set()
        c2_stuck_set = set()

        mock_processor.process_one_cycle.side_effect = [
            (c1_next_states, c1_lost_set, c1_stuck_set),
            (c2_next_states, c2_lost_set, c2_stuck_set),
        ]

        scan_thread_instance.run()

        expected_calls = [
            call(
                current_file_states={},
                previously_lost_paths=set(),
                previously_stuck_active_paths=set(),
            ),
            call(
                current_file_states=c1_next_states,
                previously_lost_paths=c1_lost_set,
                previously_stuck_active_paths=c1_stuck_set,
            ),
        ]
        mock_processor.process_one_cycle.assert_has_calls(expected_calls)
        assert mock_processor.process_one_cycle.call_count == 2

        assert scan_thread_instance._current_file_states == c2_next_states
        assert scan_thread_instance._previously_lost_paths == c2_lost_set
        assert scan_thread_instance._previously_stuck_active_paths == c2_stuck_set

        assert find_log_record(
            caplog,
            logging.INFO,
            [f"Stopping {THREAD_NAME}", "Graceful exit after 2 iterations"],
        )

    # Error Handling in Run Loop
    @pytest.mark.parametrize(
        "processor_exception, expected_log_level, log_start_substring, expect_thread_break",
        [
            (
                ScanDirectoryError(
                    directory=SCAN_DIR,
                    message="Test no-access",
                    original_exception=PermissionError(),
                ),
                logging.ERROR,
                f"{THREAD_NAME}: Critical ScanDirectoryError",
                True,
            ),
            (
                ValueError("Test unexpected processor fail"),
                logging.ERROR,
                f"{THREAD_NAME}: Unexpected error during processor cycle",
                False,
            ),
        ],
        ids=[
            "scan_directory_error_stops_thread",
            "other_processor_error_continues_loop",
        ],
    )
    def test_run_handles_processor_exceptions_and_state_preservation(
        self,
        scan_thread_instance: ScanThread,
        mock_processor: MagicMock,
        mock_stop_event: MagicMock,
        mock_monotonic_func: MagicMock,
        caplog: pytest.LogCaptureFixture,
        processor_exception: Exception,
        expected_log_level: int,
        log_start_substring: str,
        expect_thread_break: bool,
    ):
        caplog.set_level(logging.WARNING)

        num_cycles_to_run_setup = 1 if expect_thread_break else 2
        setup_stop_event_for_cycles(mock_stop_event, num_cycles=num_cycles_to_run_setup)
        setup_monotonic_time_for_cycles(
            mock_monotonic_func, num_cycles=num_cycles_to_run_setup
        )

        second_call_success_next_states = {
            Path("ok_next.dat"): MagicMock(spec=FileStateRecord)
        }
        second_call_success_lost = {Path("ok_lost.dat")}
        second_call_success_stuck = {Path("ok_stuck.dat")}

        if not expect_thread_break and num_cycles_to_run_setup > 1:
            mock_processor.process_one_cycle.side_effect = [
                processor_exception,
                (
                    second_call_success_next_states,
                    second_call_success_lost,
                    second_call_success_stuck,
                ),
            ]
        else:
            mock_processor.process_one_cycle.side_effect = processor_exception

        scan_thread_instance.run()

        if expect_thread_break:
            mock_processor.process_one_cycle.assert_called_once()
        else:
            assert (
                mock_processor.process_one_cycle.call_count == num_cycles_to_run_setup
            )

        log_entry = find_log_record(
            caplog, expected_log_level, [log_start_substring, str(SCAN_DIR)]
        )
        assert log_entry is not None, "Expected error log not found."

        if isinstance(processor_exception, ScanDirectoryError):
            assert "Thread stopping" in log_entry.getMessage()
            assert log_entry.exc_info is None
        else:
            assert log_entry.exc_info is not None
            assert log_entry.exc_info[1] is processor_exception
            if not expect_thread_break:
                warning_log = find_log_record(
                    caplog,
                    logging.WARNING,
                    [f"{THREAD_NAME} cycle 1 for", "did not complete successfully"],
                )
                assert warning_log is not None, (
                    "Warning log for failed cycle continuation not found."
                )
                assert (
                    scan_thread_instance._current_file_states
                    == second_call_success_next_states
                )
                assert (
                    scan_thread_instance._previously_lost_paths
                    == second_call_success_lost
                )
                assert (
                    scan_thread_instance._previously_stuck_active_paths
                    == second_call_success_stuck
                )

    # Wait Logic Tests
    def test_run_wait_logic_cycle_exceeds_interval(
        self,
        scan_thread_instance: ScanThread,
        mock_processor: MagicMock,
        mock_stop_event: MagicMock,
        mock_monotonic_func: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG, logger=MODULE_LOGGER)
        setup_stop_event_for_cycles(mock_stop_event, num_cycles=1)

        long_cycle_duration = SCAN_INTERVAL + 0.05
        setup_monotonic_time_for_cycles(
            mock_monotonic_func, num_cycles=1, cycle_duration=long_cycle_duration
        )

        scan_thread_instance.run()

        mock_stop_event.wait.assert_not_called()
        log_entry = find_log_record(
            caplog,
            logging.DEBUG,
            [
                f"{THREAD_NAME} scan cycle duration",
                f"({long_cycle_duration:.3f} sec) met or exceeded interval",
                f"({SCAN_INTERVAL:.1f} sec)",
            ],
        )
        assert log_entry is not None, "Log for cycle exceeding interval not found."

    def test_run_wait_logic_interrupted_by_stop(
        self,
        scan_thread_instance: ScanThread,
        mock_processor: MagicMock,
        mock_stop_event: MagicMock,
        mock_monotonic_func: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO, logger=MODULE_LOGGER)

        mock_stop_event.is_set.side_effect = [False, False, True]
        setup_monotonic_time_for_cycles(
            mock_monotonic_func, num_cycles=1, cycle_duration=MOCK_MONO_CYCLE_DURATION
        )
        mock_stop_event.wait.return_value = True

        scan_thread_instance.run()

        numerical_expected_wait_time = SCAN_INTERVAL - MOCK_MONO_CYCLE_DURATION
        mock_stop_event.wait.assert_called_once_with(
            pytest.approx(numerical_expected_wait_time)
        )
        assert find_log_record(
            caplog, logging.INFO, [f"{THREAD_NAME} wait interrupted by stop signal."]
        )

    @pytest.mark.parametrize(
        "interval_to_test", [0.0, -1.0], ids=["zero_interval", "negative_interval"]
    )
    def test_run_with_zero_or_negative_scan_interval(
        self,
        scan_thread_instance: ScanThread,
        mock_processor: MagicMock,
        mock_stop_event: MagicMock,
        mock_monotonic_func: MagicMock,
        caplog: pytest.LogCaptureFixture,
        interval_to_test: float,
    ):
        """Tests behavior with scan_interval_seconds <= 0."""
        caplog.set_level(logging.DEBUG, logger=MODULE_LOGGER)
        scan_thread_instance.scan_interval_seconds = interval_to_test

        setup_stop_event_for_cycles(mock_stop_event, num_cycles=2)
        setup_monotonic_time_for_cycles(
            mock_monotonic_func, num_cycles=2, cycle_duration=0.01
        )

        scan_thread_instance.run()

        assert mock_processor.process_one_cycle.call_count == 2
        mock_stop_event.wait.assert_not_called()

        logs_found_count = 0
        for record in caplog.records:
            if (
                record.levelno == logging.DEBUG
                and f"{THREAD_NAME} scan cycle duration" in record.getMessage()
                and "met or exceeded interval" in record.getMessage()
            ):
                # CORRECTED: Do not use abs() here, SUT logs the interval as-is.
                assert f"({interval_to_test:.1f} sec)" in record.getMessage()
                logs_found_count += 1
        assert logs_found_count == 2, (
            "Expected log for immediate next cycle for both cycles."
        )


class TestScanThreadStop:
    def test_stop_method_sets_event_and_logs_info(
        self,
        scan_thread_instance: ScanThread,
        mock_stop_event: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO, logger=MODULE_LOGGER)
        mock_stop_event.is_set.return_value = False

        scan_thread_instance.stop()

        mock_stop_event.set.assert_called_once()
        assert find_log_record(
            caplog,
            logging.INFO,
            [f"{THREAD_NAME} received stop signal", "requesting shutdown"],
        )

    def test_stop_method_when_already_set_logs_debug(
        self,
        scan_thread_instance: ScanThread,
        mock_stop_event: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG, logger=MODULE_LOGGER)
        mock_stop_event.is_set.return_value = True

        scan_thread_instance.stop()

        mock_stop_event.set.assert_not_called()
        assert find_log_record(
            caplog, logging.DEBUG, [f"{THREAD_NAME} is already stopping or has stopped"]
        )
