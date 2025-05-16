import logging
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

# --- Test Target ---
from datamover.scanner.process_scan_results import process_scan_results
from datamover.scanner.file_state_record import FileStateRecord
from datamover.file_functions.gather_entry_data import GatheredEntryData

# --- Test Helpers ---
from tests.test_utils.logging_helpers import find_log_record


MODULE = "datamover.scanner.process_scan_results"  # Module where functions to be patched are looked up

# --- Fixtures ---


@pytest.fixture
def sample_paths() -> dict[str, Path]:  # Updated type hint
    """Provides a dictionary of sample Path objects for test consistency."""
    base = Path("/test/scan_dir")
    return {
        "file1": base / "file1.dat",  # Normal, existing
        "file2": base / "file2.log",  # Becomes lost
        "file3": base / "file3.tmp",  # Becomes stuck active
        "file4": base / "file4.pcap",  # Will be removed (was in existing_states)
        "file5_new": base / "file5_new.dat",  # New file
        "file6_new_stuck": base
        / "file6_stuck.dat",  # New but meets stuck criteria via mocks
        "file7_long_not_active": base / "file7_long.dat",  # Present long, not active
        "file8_active_not_long": base / "file8_active.dat",  # Active, not long
    }


@pytest.fixture
def current_times() -> dict[str, float]:  # Updated type hint
    """Provides fixed current wall and monotonic times for deterministic tests."""
    return {"wall": 1700000000.0, "mono": 5000.0}


@pytest.fixture
def mock_update_state(mocker) -> MagicMock:  # Removed MockerFixture type hint
    """Mocks the update_file_state_record dependency."""
    return mocker.patch(
        f"{MODULE}.update_file_state_record",
        return_value=({}, set()),  # Default simple return
        autospec=True,
    )


@pytest.fixture
def mock_is_lost(mocker) -> MagicMock:  # Removed MockerFixture type hint
    """Mocks the is_file_lost dependency."""
    return mocker.patch(f"{MODULE}.is_file_lost", return_value=False, autospec=True)


@pytest.fixture
def mock_is_active(mocker) -> MagicMock:  # Removed MockerFixture type hint
    """Mocks the is_active_since_last_scan dependency."""
    return mocker.patch(
        f"{MODULE}.is_active_since_last_scan", return_value=False, autospec=True
    )


@pytest.fixture
def mock_is_present(mocker) -> MagicMock:  # Removed MockerFixture type hint
    """Mocks the is_file_present_too_long dependency."""
    return mocker.patch(
        f"{MODULE}.is_file_present_too_long", return_value=False, autospec=True
    )


# --- Parametrized tests for edge cases with no scan data ---


@pytest.mark.parametrize(
    "existing_states_param, mock_update_return_val, expected_next_states_val, expected_removed_paths_val",
    [
        pytest.param({}, ({}, set()), {}, set(), id="no_files_initially_or_now"),
        pytest.param(
            {Path("a"): MagicMock(spec=FileStateRecord)},
            ({}, {Path("a")}),
            {},
            {Path("a")},
            id="all_previously_tracked_files_removed",
        ),
    ],
)
def test_no_gathered_data_scenarios(
    existing_states_param: dict[Path, FileStateRecord],  # Updated type hint
    mock_update_return_val: tuple[dict, set],  # Updated type hint
    expected_next_states_val: dict,  # Updated type hint
    expected_removed_paths_val: set,  # Updated type hint
    mock_update_state: MagicMock,
    mock_is_lost: MagicMock,
    mock_is_active: MagicMock,
    mock_is_present: MagicMock,
    caplog: pytest.LogCaptureFixture,
    current_times: dict[str, float],  # Updated type hint
):
    """
    Tests scenarios where no files are gathered in the current scan.
    Verifies `update_file_state_record` is called and its results are passed through,
    and that no file checks (lost, active, present) occur.
    """
    caplog.set_level(logging.DEBUG, logger=MODULE)
    mock_update_state.return_value = mock_update_return_val

    result = process_scan_results(
        gathered_data=[],
        existing_states=existing_states_param,
        lost_timeout=10.0,
        stuck_active_timeout=20.0,
        monotonic_now=current_times["mono"],
        wall_now=current_times["wall"],
    )

    assert isinstance(result, tuple) and len(result) == 4
    next_s, removed_p, lost_p, stuck_p = result

    assert next_s == expected_next_states_val
    assert removed_p == expected_removed_paths_val
    assert lost_p == set()
    assert stuck_p == set()

    mock_update_state.assert_called_once_with(
        existing_file_states=existing_states_param,
        gathered_data=[],
        monotonic_time_now=current_times["mono"],
    )
    mock_is_lost.assert_not_called()
    mock_is_active.assert_not_called()
    mock_is_present.assert_not_called()

    assert (
        find_log_record(caplog, logging.DEBUG, ["Processing scan results"]) is not None
    )
    assert find_log_record(caplog, logging.DEBUG, ["State update complete"]) is not None
    assert (
        find_log_record(caplog, logging.DEBUG, ["Problem file checks complete"])
        is not None
    )


# --- Complex scenario test ---


def test_complex_scenario(
    sample_paths: dict[str, Path],  # Updated type hint
    current_times: dict[str, float],  # Updated type hint
    mock_update_state: MagicMock,
    mock_is_lost: MagicMock,
    mock_is_active: MagicMock,
    mock_is_present: MagicMock,
    caplog: pytest.LogCaptureFixture,
):
    """
    Tests a complex scenario involving a mix of file states, verifying
    classification, return values, mock calls, and INFO logs.
    """
    caplog.set_level(logging.INFO, logger=MODULE)  # Focus on INFO logs for this test

    # --- Arrange ---
    p1_normal = sample_paths["file1"]
    p2_becomes_lost = sample_paths["file2"]
    p3_becomes_stuck = sample_paths["file3"]
    p4_is_removed = sample_paths["file4"]
    p5_is_new = sample_paths["file5_new"]
    p7_long_not_active = sample_paths["file7_long_not_active"]
    p8_active_not_long = sample_paths["file8_active_not_long"]

    st_p1 = MagicMock(spec=FileStateRecord, name="StateNormal")
    st_p2 = MagicMock(
        spec=FileStateRecord,
        name="StateLost",
        path=p2_becomes_lost,
        mtime_wall=current_times["wall"] - 20,
    )  # mtime for lost log
    st_p3 = MagicMock(
        spec=FileStateRecord,
        name="StateStuck",
        path=p3_becomes_stuck,
        first_seen_mono=current_times["mono"] - 30,
    )  # first_seen for stuck log
    st_p5 = MagicMock(spec=FileStateRecord, name="StateNew")
    st_p7 = MagicMock(
        spec=FileStateRecord,
        name="StateLongNotActive",
        path=p7_long_not_active,
        first_seen_mono=current_times["mono"] - 30,
    )  # first_seen for log
    st_p8 = MagicMock(spec=FileStateRecord, name="StateActiveNotLong")

    mocked_next_states: dict[Path, FileStateRecord] = {  # Updated type hint
        p1_normal: st_p1,
        p2_becomes_lost: st_p2,
        p3_becomes_stuck: st_p3,
        p5_is_new: st_p5,
        p7_long_not_active: st_p7,
        p8_active_not_long: st_p8,
    }
    mocked_removed_paths: set[Path] = {p4_is_removed}  # Updated type hint
    mock_update_state.return_value = (mocked_next_states, mocked_removed_paths)

    existing_paths: set[Path] = {  # Updated type hint
        p1_normal,
        p2_becomes_lost,
        p3_becomes_stuck,
        p4_is_removed,
        p7_long_not_active,
        p8_active_not_long,
    }
    existing_states: dict[Path, FileStateRecord] = {  # Updated type hint
        path: MagicMock(spec=FileStateRecord, name=f"Existing_{path.name}")
        for path in existing_paths
    }

    # Configure mock helper behaviors
    # is_file_lost called with (state, wall_time_now, lost_timeout)
    mock_is_lost.side_effect = lambda state, wall_time_now, lost_timeout: state is st_p2
    # is_active_since_last_scan called with (record)
    mock_is_active.side_effect = lambda record: record in [st_p3, st_p8]
    # is_file_present_too_long called with (state, monotonic_time_now, presence_timeout)
    mock_is_present.side_effect = (
        lambda state, monotonic_time_now, presence_timeout: state in [st_p3, st_p7]
    )

    lost_timeout_val = 10.0
    stuck_active_timeout_val = 15.0

    # --- Act ---
    result = process_scan_results(
        gathered_data=[MagicMock(spec=GatheredEntryData)],
        existing_states=existing_states,
        lost_timeout=lost_timeout_val,
        stuck_active_timeout=stuck_active_timeout_val,
        monotonic_now=current_times["mono"],
        wall_now=current_times["wall"],
    )
    next_s, removed_p, lost_p, stuck_p = result

    # --- Assert Return Values ---
    assert next_s == mocked_next_states
    assert removed_p == mocked_removed_paths
    assert lost_p == {p2_becomes_lost}
    assert stuck_p == {p3_becomes_stuck}

    # --- Assert Mock Calls (Order and Arguments) ---
    expected_lost_calls = [
        call(
            state=st, wall_time_now=current_times["wall"], lost_timeout=lost_timeout_val
        )
        for p, st in mocked_next_states.items()
        if p in existing_paths
    ]
    assert mock_is_lost.call_args_list == expected_lost_calls

    expected_active_calls = [call(record=st) for st in mocked_next_states.values()]
    assert mock_is_active.call_args_list == expected_active_calls

    expected_present_calls = [
        call(
            state=st,
            monotonic_time_now=current_times["mono"],
            presence_timeout=stuck_active_timeout_val,
        )
        for st in mocked_next_states.values()
    ]
    assert mock_is_present.call_args_list == expected_present_calls

    # --- Assert INFO Logs (Precise Check using find_log_record) ---
    lost_log = find_log_record(
        caplog, logging.INFO, ["Identified file as LOST", str(p2_becomes_lost)]
    )
    assert lost_log is not None
    # Example of checking args if needed: assert lost_log.args[3] == pytest.approx(lost_timeout_val)

    stuck_log = find_log_record(
        caplog, logging.INFO, ["Identified file as STUCK ACTIVE", str(p3_becomes_stuck)]
    )
    assert stuck_log is not None

    present_long_log = find_log_record(
        caplog,
        logging.INFO,
        ["File", str(p7_long_not_active), "present too long", "but NOT active"],
    )
    assert present_long_log is not None


# --- New-file stuck-active scenario ---


def test_new_file_can_be_stuck(
    sample_paths: dict[str, Path],
    current_times: dict[str, float],
    mock_update_state: MagicMock,
    mock_is_lost: MagicMock,
    mock_is_active: MagicMock,
    mock_is_present: MagicMock,
):
    """
    Tests a new file can be 'stuck active' if helpers report it as active and present too long.
    Also verifies it's not checked for 'lost' status.
    """
    p_new = sample_paths["file6_new_stuck"]
    # Create a dummy FileStateRecord and give it the two timestamps
    st_new = MagicMock(spec=FileStateRecord, name="StateNewStuck")
    st_new.first_seen_mono = current_times["mono"]
    st_new.first_seen_wall = current_times["wall"]

    # Have update_file_state_record return our new state
    mock_update_state.return_value = ({p_new: st_new}, set())

    # Helpers behavior
    mock_is_lost.return_value = False
    mock_is_active.return_value = True
    mock_is_present.return_value = True

    stuck_timeout_val = 1.0  # For the call assertion

    # Call under test
    next_states, removed_paths, lost_paths, stuck_paths = process_scan_results(
        gathered_data=[MagicMock(spec=GatheredEntryData)],
        existing_states={},
        lost_timeout=5.0,
        stuck_active_timeout=stuck_timeout_val,
        monotonic_now=current_times["mono"],
        wall_now=current_times["wall"],
    )

    # Assertions – make sure it appears in “stuck” and not in “lost”
    assert p_new in stuck_paths
    assert p_new not in lost_paths
    assert next_states[p_new] is st_new
    assert removed_paths == set()
