import logging
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock

import pytest

from datamover.file_functions.file_exceptions import ScanDirectoryError
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.queues.queue_functions import QueuePutError
from datamover.scanner.do_single_cycle import DoSingleCycle
from datamover.scanner.file_state_record import FileStateRecord

# --- Test Target ---

# --- Test Helpers ---
from tests.test_utils.logging_helpers import find_log_record

MODULE = "datamover.scanner.do_single_cycle"
SCAN_DIR = Path("/resolved/scan_dir")
EXT = "pcap"
LOST_T = 20.0
STUCK_T = 30.0
MOCK_WALL = 1700000100.0
MOCK_MONO = 6000.0


# --- Fixtures ---
@pytest.fixture
def mock_lost_file_queue() -> MagicMock:
    """Queue mock for lost files."""
    return MagicMock(spec=Queue)


@pytest.fixture
def processor(mock_fs: MagicMock, mock_lost_file_queue: MagicMock) -> DoSingleCycle:
    """DoSingleCycle instance with injected time, fs, and queue mocks."""
    return DoSingleCycle(
        validated_directory_to_scan=SCAN_DIR,
        extension_to_scan_no_dot=EXT,
        lost_timeout=LOST_T,
        stuck_active_file_timeout=STUCK_T,
        lost_file_queue=mock_lost_file_queue,
        time_func=lambda: MOCK_WALL,
        monotonic_func=lambda: MOCK_MONO,
        fs=mock_fs,
    )


@pytest.fixture
def patch_scan(mocker) -> MagicMock:
    return mocker.patch(f"{MODULE}.scan_directory_and_filter", autospec=True)


@pytest.fixture
def patch_process(mocker) -> MagicMock:
    return mocker.patch(f"{MODULE}.process_scan_results", autospec=True)


@pytest.fixture
def patch_report(mocker) -> MagicMock:
    return mocker.patch(f"{MODULE}.report_state_changes", autospec=True)


@pytest.fixture
def patch_put(mocker) -> MagicMock:
    return mocker.patch(f"{MODULE}.safe_put", autospec=True)


@pytest.fixture
def initial_state() -> tuple[
    dict[Path, FileStateRecord], set[Path], set[Path]
]:  # Updated
    """Return a tuple of (current_states, previously_lost, previously_stuck)."""
    p1 = SCAN_DIR / "a.dat"
    p2 = SCAN_DIR / "b.dat"
    current_states: dict[Path, FileStateRecord] = {
        p1: MagicMock(spec=FileStateRecord)
    }  # Updated
    previously_lost: set[Path] = {p2}  # Updated
    previously_stuck: set[Path] = set()  # Updated
    return current_states, previously_lost, previously_stuck


# --- Scan directory error handling ---
@pytest.mark.parametrize(
    "side_effect_exception, expected_exception_type, log_level, log_msg_substrings, is_wrapped",
    [
        (
            ScanDirectoryError(
                message="scan fail",
                directory=SCAN_DIR,
                original_exception=ValueError("orig scan error"),
            ),
            ScanDirectoryError,
            logging.ERROR,
            ["ScanDirectoryError during scan for", str(SCAN_DIR)],
            False,
        ),
        (
            ValueError("unexpected boom from scan"),
            ScanDirectoryError,
            logging.ERROR,
            ["Unexpected error during scan_directory_and_filter", str(SCAN_DIR)],
            True,
        ),
    ],
    ids=["propagate_scan_dir_error", "wrap_unexpected_scan_error"],
)
def test_process_one_cycle_scan_errors(
    processor: DoSingleCycle,
    initial_state: tuple[dict[Path, FileStateRecord], set[Path], set[Path]],  # Updated
    patch_scan: MagicMock,
    side_effect_exception: Exception,
    expected_exception_type: type[Exception],
    log_level: int,
    log_msg_substrings: list[str],  # Updated
    is_wrapped: bool,
    caplog: pytest.LogCaptureFixture,
):
    """Tests handling of errors from the scan_directory_and_filter phase."""
    caplog.set_level(log_level)
    patch_scan.side_effect = side_effect_exception
    current, lost, stuck = initial_state

    with pytest.raises(expected_exception_type) as exc_info:
        processor.process_one_cycle(current, lost, stuck)

    if is_wrapped:
        assert exc_info.value.__cause__ is side_effect_exception
    else:
        assert exc_info.value is side_effect_exception

    entry = find_log_record(caplog, log_level, log_msg_substrings)
    assert entry is not None, "Expected error log not found"
    if is_wrapped:
        assert entry.exc_info and entry.exc_info[1] is side_effect_exception
        assert str(side_effect_exception) in entry.exc_text


# --- process_scan_results error handling ---
def test_process_one_cycle_process_scan_results_fails(
    processor: DoSingleCycle,
    initial_state: tuple[dict[Path, FileStateRecord], set[Path], set[Path]],  # Updated
    patch_scan: MagicMock,
    patch_process: MagicMock,
    caplog: pytest.LogCaptureFixture,
):
    """Tests that if process_scan_results fails, previous state is returned and error logged."""
    caplog.set_level(logging.ERROR)
    current, lost, stuck = initial_state
    patch_scan.return_value = [MagicMock(spec=GatheredEntryData)]
    process_error = ValueError("Core processing logic failed")
    patch_process.side_effect = process_error

    next_s, next_l, next_st = processor.process_one_cycle(current, lost, stuck)

    assert next_s is current, "Should return original current_states"
    assert next_l is lost, "Should return original previously_lost"
    assert next_st is stuck, "Should return original previously_stuck"

    entry = find_log_record(
        caplog,
        logging.ERROR,
        ["Processor error during process_scan_results", str(SCAN_DIR)],
    )
    assert entry is not None, "Error log for process_scan_results failure not found"
    assert entry.exc_info and entry.exc_info[1] is process_error
    assert str(process_error) in entry.exc_text


# --- Delta calculation failure ---
def test_process_one_cycle_delta_calc_fails_returns_previous(
    processor: DoSingleCycle,
    initial_state: tuple[dict[Path, FileStateRecord], set[Path], set[Path]],  # Updated
    patch_scan: MagicMock,
    patch_process: MagicMock,
    patch_report: MagicMock,
    patch_put: MagicMock,
    caplog: pytest.LogCaptureFixture,
):
    """Tests that if delta calculation fails, previous state is returned and error logged."""
    caplog.set_level(logging.ERROR)
    current, lost, stuck = initial_state
    patch_scan.return_value = []
    patch_process.return_value = (
        {SCAN_DIR / "f.pcap": MagicMock(spec=FileStateRecord)},
        set(),
        "not-a-set",
        set(),
    )

    next_s, next_l, next_st = processor.process_one_cycle(current, lost, stuck)

    assert next_s is current and next_l is lost and next_st is stuck
    patch_report.assert_not_called()
    patch_put.assert_not_called()

    entry = find_log_record(
        caplog,
        logging.ERROR,
        ["Processor error calculating problem file deltas", str(SCAN_DIR)],
    )
    assert entry and entry.exc_info and entry.exc_info[0] is TypeError


# --- report_state_changes error handling ---
def test_process_one_cycle_report_state_changes_fails_logs_error(
    processor: DoSingleCycle,
    initial_state: tuple[dict[Path, FileStateRecord], set[Path], set[Path]],  # Updated
    patch_scan: MagicMock,
    patch_process: MagicMock,
    patch_report: MagicMock,
    patch_put: MagicMock,
    caplog: pytest.LogCaptureFixture,
):
    """Tests that if report_state_changes fails, an error is logged and enqueuing is skipped."""
    caplog.set_level(logging.DEBUG)
    current, prev_lost, prev_stuck = initial_state

    p_newly_lost = SCAN_DIR / "newly_lost_for_report_fail.pcap"
    mock_gathered_data = [MagicMock(spec=GatheredEntryData)]
    patch_scan.return_value = mock_gathered_data

    expected_next_states_from_process: dict[Path, FileStateRecord] = {
        p_newly_lost: MagicMock(spec=FileStateRecord)
    }  # Updated

    patch_process.return_value = (
        expected_next_states_from_process,
        set(),
        {p_newly_lost},
        set(),
    )
    report_error = ValueError("Reporting failed")
    patch_report.side_effect = report_error

    next_s, next_l, next_st = processor.process_one_cycle(
        current, prev_lost, prev_stuck
    )

    assert next_s == expected_next_states_from_process
    assert next_l == {p_newly_lost}
    assert next_st == set()

    patch_report.assert_called_once()
    patch_put.assert_not_called()

    entry = find_log_record(
        caplog,
        logging.ERROR,
        ["Processor error during reporting or queuing phase", str(SCAN_DIR)],
    )
    assert entry is not None, "Error log for reporting/queuing phase failure not found"
    assert entry.exc_info and entry.exc_info[1] is report_error


# --- Enqueue variations (none, one, multiple) and Happy Path Logging ---
@pytest.mark.parametrize(
    "next_states_param, lost_set_param, expected_puts, expect_info_log, test_id",
    [
        ({}, set(), 0, False, "none_lost"),
        (
            {(Path(SCAN_DIR / "one.pcap")): MagicMock(spec=FileStateRecord)},
            {Path(SCAN_DIR / "one.pcap")},
            1,
            True,
            "one_lost",
        ),
        (
            {
                (Path(SCAN_DIR / "a.pcap")): MagicMock(spec=FileStateRecord),
                (Path(SCAN_DIR / "b.pcap")): MagicMock(spec=FileStateRecord),
            },
            {Path(SCAN_DIR / "a.pcap"), Path(SCAN_DIR / "b.pcap")},
            2,
            True,
            "two_lost",
        ),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_enqueue_variations_and_happy_path_logs(
    processor: DoSingleCycle,
    initial_state: tuple[dict[Path, FileStateRecord], set[Path], set[Path]],  # Updated
    patch_scan: MagicMock,
    patch_process: MagicMock,
    patch_report: MagicMock,
    patch_put: MagicMock,
    caplog: pytest.LogCaptureFixture,
    next_states_param: dict[Path, FileStateRecord],
    lost_set_param: set[Path],  # Updated
    expected_puts: int,
    expect_info_log: bool,
    test_id: str,
):
    """Tests enqueuing logic and detailed debug logs for successful paths."""
    caplog.set_level(logging.DEBUG)

    mock_gathered_data = [
        MagicMock(spec=GatheredEntryData, path=SCAN_DIR / "scanned.pcap")
    ]
    patch_scan.return_value = mock_gathered_data

    patch_process.return_value = (next_states_param, set(), lost_set_param, set())

    current_states_map, previously_lost_set, previously_stuck_set = initial_state

    res_next, res_lost, res_stuck = processor.process_one_cycle(
        current_states_map, previously_lost_set, previously_stuck_set
    )

    assert res_next == next_states_param
    assert res_lost == lost_set_param
    assert res_stuck == set()

    patch_scan.assert_called_once_with(
        directory=processor.directory_to_scan,
        fs=processor.fs,
        extension_no_dot=processor.extension_no_dot,
    )
    patch_process.assert_called_once_with(
        gathered_data=mock_gathered_data,
        existing_states=current_states_map,
        lost_timeout=LOST_T,
        stuck_active_timeout=STUCK_T,
        monotonic_now=MOCK_MONO,
        wall_now=MOCK_WALL,
    )

    newly_lost_paths = lost_set_param - previously_lost_set
    patch_report.assert_called_once_with(
        newly_lost_paths=newly_lost_paths,
        newly_stuck_active_paths=set(),
        removed_tracking_paths=set(),
        lost_timeout=LOST_T,
        stuck_active_timeout=STUCK_T,
    )
    assert patch_put.call_count == expected_puts

    info_log = find_log_record(
        caplog,
        logging.INFO,
        ["Processor enqueuing", str(expected_puts), "newly identified 'lost' files"],
    )
    if expect_info_log:
        assert info_log is not None, (
            f"Expected INFO log for enqueuing {expected_puts} files not found for {test_id}"
        )
    else:
        assert info_log is None, (
            f"INFO log for enqueuing should not be present for {test_id} with 0 puts"
        )

    if expected_puts > 0:
        assert find_log_record(
            caplog, logging.DEBUG, ["Processor starting cycle", str(SCAN_DIR)]
        )
        assert find_log_record(
            caplog,
            logging.DEBUG,
            ["Scan found", str(len(mock_gathered_data)), f"'.{EXT}'"],
        )
        assert find_log_record(
            caplog,
            logging.DEBUG,
            ["Processor results for", f"{len(next_states_param)} next states"],
        )
        assert find_log_record(
            caplog,
            logging.DEBUG,
            ["Processor deltas for", f"{len(newly_lost_paths)} newly lost"],
        )
        for path_enqueued in newly_lost_paths:
            enqueued_debug_log = find_log_record(
                caplog,
                logging.DEBUG,
                ["Processor enqueued 'lost' file:", str(path_enqueued)],
            )
            assert enqueued_debug_log is not None, (
                f"Debug log for enqueued file {path_enqueued} not found for {test_id}"
            )

    for path_to_put in newly_lost_paths:
        patch_put.assert_any_call(
            item=path_to_put,
            output_queue=processor.lost_file_queue,
            queue_name=processor.lost_queue_name,
        )


# --- Failures during _enqueue_lost_files (safe_put raises error) ---
@pytest.mark.parametrize(
    "put_side_effect_exception, expected_log_level, log_msg_main_part, check_exc_info_type",
    [
        (
            QueuePutError("simulated queue full"),
            logging.ERROR,
            "Processor QueuePutError enqueuing 'lost' file",
            None,
        ),
        (
            OSError("simulated disk I/O error"),
            logging.ERROR,
            "Processor unexpected error enqueuing 'lost' file",
            OSError,
        ),
    ],
    ids=["safe_put_qput_error", "safe_put_os_error"],
)
def test_process_one_cycle_safe_put_fails_in_enqueue_loop(
    processor: DoSingleCycle,
    initial_state: tuple[dict[Path, FileStateRecord], set[Path], set[Path]],  # Updated
    patch_scan: MagicMock,
    patch_process: MagicMock,
    patch_report: MagicMock,
    patch_put: MagicMock,
    caplog: pytest.LogCaptureFixture,
    put_side_effect_exception: Exception,
    expected_log_level: int,
    log_msg_main_part: str,
    check_exc_info_type: type[Exception] | None,
):
    """Tests error logging when safe_put fails during the enqueue loop."""
    caplog.set_level(logging.DEBUG)
    current_states, previously_lost, _ = initial_state

    patch_scan.return_value = []

    file_to_fail_enqueue = SCAN_DIR / "fail_enqueue.pcap"
    expected_next_states_from_process: dict[Path, FileStateRecord] = {
        file_to_fail_enqueue: MagicMock(spec=FileStateRecord)
    }  # Updated

    patch_process.return_value = (
        expected_next_states_from_process,
        set(),
        {file_to_fail_enqueue},
        set(),
    )
    patch_put.side_effect = put_side_effect_exception

    next_s, current_l, current_sa = processor.process_one_cycle(
        current_states, previously_lost, set()
    )

    assert next_s == expected_next_states_from_process
    assert current_l == {file_to_fail_enqueue}
    assert current_sa == set()

    patch_report.assert_called_once()
    patch_put.assert_called_once_with(
        item=file_to_fail_enqueue,
        output_queue=processor.lost_file_queue,
        queue_name=processor.lost_queue_name,
    )

    # log_msg_substrings: list[str] was used in the previous parametrize, using main part here
    full_expected_substrings = [log_msg_main_part, str(file_to_fail_enqueue)]
    log_entry = find_log_record(caplog, expected_log_level, full_expected_substrings)
    assert log_entry is not None, "Specific error log for safe_put failure not found."

    if check_exc_info_type:
        assert log_entry.exc_info is not None
        assert log_entry.exc_info[0] is check_exc_info_type
        assert log_entry.exc_info[1] is put_side_effect_exception
