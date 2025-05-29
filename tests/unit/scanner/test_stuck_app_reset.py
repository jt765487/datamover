import logging
from pathlib import Path
from typing import Optional, Tuple, List, Set

import pytest

from datamover.scanner.stuck_app_reset import (
    get_app_name_from_path,
    determine_app_restart_actions,
)

# --- Test Helper ---
from tests.test_utils.logging_helpers import find_log_record

# --- Test Target ---
MODULE_LOGGER_NAME = "datamover.scanner.stuck_app_reset"

# --- Fixture for Restart Directory ---
RESTART_DIR = Path("/test/restarts")

# --- Tests for get_app_name_from_path ---

# Parameter: input_filename, expected_app_name, expect_warning_log
# expect_warning_log is a boolean to indicate if a warning is expected.
# The logged filename will be derived from input_filename.
GET_APP_NAME_TEST_CASES: List[Tuple[str, Optional[str], bool]] = [
    # Valid Cases (expect_warning_log = False)
    ("APP1-20230101-120000.pcap", "APP1", False),
    (
        "XYZ-ABC-20230101-12-00-00.log",
        "XYZ",
        False,
    ),  # Corrected as per plan (first hyphen)
    ("APP123-20230101-120000.pcap", "APP123", False),
    ("A-20230101-120000.pcap", "A", False),
    ("MYAPP-20230101-120000", "MYAPP", False),  # No extension
    (
        "APP7-20230101-120000.pcap",
        "APP7",
        False,
    ),  # Path component handled by Path() in test
    # Invalid Cases (expect_warning_log = True)
    ("APP120230101120000.pcap", None, True),  # No hyphen
    ("-20230101-120000.pcap", None, True),  # Starts with hyphen
    ("", None, True),  # Empty filename
    ("-", None, True),  # Only hyphen
    ("---", None, True),  # Multiple hyphens only
    (".pcap", None, True),  # Filename is just an extension
]


@pytest.mark.parametrize(
    "input_filename, expected_app_name, expect_warning_log",
    GET_APP_NAME_TEST_CASES,
    ids=[
        # Valid
        "valid_standard",
        "valid_multiple_hyphens_in_suffix",
        "valid_app_name_with_numbers",
        "valid_short_app_name",
        "valid_no_extension",
        "valid_with_path_component",  # Path() handles this; input_filename is just name
        # Invalid
        "invalid_no_hyphen",
        "invalid_starts_with_hyphen",
        "invalid_empty_filename",
        "invalid_only_hyphen",
        "invalid_multiple_hyphens_only",
        "invalid_only_extension",
    ],
)
def test_get_app_name_from_path(
    caplog: pytest.LogCaptureFixture,
    input_filename: str,
    expected_app_name: Optional[str],
    expect_warning_log: bool,
):
    """
    Tests get_app_name_from_path for various valid and invalid filenames.
    Verifies the returned app name and logging behavior.
    """
    file_path = (
        Path(f"/dummy_dir/{input_filename}") if input_filename else Path(input_filename)
    )

    if expect_warning_log:
        caplog.set_level(logging.WARNING, logger=MODULE_LOGGER_NAME)
    else:
        # Set to a higher level or check for absence of WARNING specifically
        caplog.set_level(logging.CRITICAL, logger=MODULE_LOGGER_NAME)

    # Act
    actual_app_name = get_app_name_from_path(file_path)

    # Assert return value
    assert actual_app_name == expected_app_name

    # Assert logging behavior
    if expect_warning_log:
        expected_log_substrings = [
            "Could not extract App Name",  # Match SUT log message
            repr(file_path.name),  # Function logs file_path.name
        ]
        log_entry = find_log_record(caplog, logging.WARNING, expected_log_substrings)
        assert log_entry is not None, (
            f"Expected WARNING log for '{file_path.name}' not found or incorrect. "
            f"Actual logs: {[r.message for r in caplog.records if r.levelno == logging.WARNING]}"
        )
    else:
        for record in caplog.records:
            if record.levelno == logging.WARNING and record.name == MODULE_LOGGER_NAME:
                pytest.fail(f"Unexpected WARNING log found: {record.message}")


def test_get_app_name_from_path_with_full_path_structure(
    caplog: pytest.LogCaptureFixture,
):
    """Ensures path components don't interfere with name extraction."""
    caplog.set_level(logging.CRITICAL, logger=MODULE_LOGGER_NAME)  # Expect no warning
    file_path = Path("/var/data/INPUTAPP-20231010-000000.pcap")
    expected_app_name = "INPUTAPP"

    actual_app_name = get_app_name_from_path(file_path)

    assert actual_app_name == expected_app_name
    # Verify no warning log
    for record in caplog.records:
        if record.levelno == logging.WARNING and record.name == MODULE_LOGGER_NAME:
            pytest.fail(f"Unexpected WARNING log found for full path: {record.message}")


# --- Tests for determine_app_restart_actions ---

DetermineActionsTestCase = Tuple[
    Set[str],
    Set[str],
    Set[str],
    Set[str],
    Optional[str],
    Optional[str],
    str,  # Added test_id
]

DETERMINE_ACTIONS_TEST_CASES_DATA: List[DetermineActionsTestCase] = [
    # A. Basic States
    (
        set(),
        set(),
        set(),
        set(),
        None,
        "No applications currently stuck.",
        "basic_no_stuck_no_previous",
    ),
    (
        set(),
        {"APP1", "APP2"},
        set(),
        set(),
        None,
        "No applications currently stuck.",
        "basic_no_stuck_had_previous",
    ),
    # B. New Stuck Applications
    (
        {"APP1-ts1.pcap"},
        set(),
        {"APP1.restart"},
        {"APP1"},
        "Newly stuck applications identified for restart signal: APP1",
        None,
        "new_one_stuck_no_previous",
    ),
    (
        {"APP1-ts1.pcap", "APP2-ts2.pcap"},
        set(),
        {"APP1.restart", "APP2.restart"},
        {"APP1", "APP2"},
        "Newly stuck applications identified for restart signal: APP1, APP2",
        None,
        "new_multi_stuck_no_previous",
    ),
    (
        {"APP1-ts1.pcap", "APP1-ts2.pcap"},
        set(),
        {"APP1.restart"},
        {"APP1"},
        "Newly stuck applications identified for restart signal: APP1",
        None,
        "new_multi_files_same_app_no_previous",
    ),
    # C. Existing Stuck Applications
    (
        {"APP1-ts1.pcap"},
        {"APP1"},
        set(),
        {"APP1"},
        None,
        "No new applications require a restart signal. Currently stuck applications (APP1)",
        "existing_one_stuck_was_previous",
    ),
    (
        {"APP1-ts1.pcap", "APP1-ts2.pcap"},
        {"APP1"},
        set(),
        {"APP1"},
        None,
        "No new applications require a restart signal. Currently stuck applications (APP1)",
        "existing_multi_files_same_app_was_previous",
    ),
    # D. Mixed Scenarios
    (
        {"APP1-ts1.pcap", "APP2-ts2.pcap", "APP3-ts3.pcap"},
        {"APP1", "APP2"},
        {"APP3.restart"},
        {"APP1", "APP2", "APP3"},
        "Newly stuck applications identified for restart signal: APP3",
        None,
        "mixed_new_and_existing",
    ),
    (
        {"APP2-ts2.pcap", "APP3-ts3.pcap"},
        {"APP1", "APP2"},
        {"APP3.restart"},
        {"APP2", "APP3"},
        "Newly stuck applications identified for restart signal: APP3",
        None,
        "mixed_some_unstuck_new_and_existing",
    ),
    # E. Edge Cases for App Name Extraction
    (
        {"APP1-ts1.pcap", "INVALIDFILE.log"},
        set(),
        {"APP1.restart"},
        {"APP1"},
        "Newly stuck applications identified for restart signal: APP1",
        None,
        "edge_invalid_name_mixed",
    ),
    (
        {"INVALIDFILE.log", "-ts.pcap"},
        set(),
        set(),
        set(),
        None,
        "No applications currently stuck.",
        "edge_all_invalid_names",
    ),
]

# Extract just the ids for the parametrize decorator
DETERMINE_ACTIONS_TEST_IDS = [case[-1] for case in DETERMINE_ACTIONS_TEST_CASES_DATA]


@pytest.mark.parametrize(
    "current_stuck_files_str, previously_signaled_apps, "
    "expected_restart_files_str, expected_current_stuck_apps, "
    "expected_info_log_substr, expected_debug_log_substr, test_id",  # Added test_id to params
    DETERMINE_ACTIONS_TEST_CASES_DATA,
    ids=DETERMINE_ACTIONS_TEST_IDS,
)
def test_determine_app_restart_actions(
    caplog: pytest.LogCaptureFixture,
    current_stuck_files_str: Set[str],
    previously_signaled_apps: Set[str],
    expected_restart_files_str: Set[str],
    expected_current_stuck_apps: Set[str],
    expected_info_log_substr: Optional[str],
    expected_debug_log_substr: Optional[str],
    test_id: str,  # Added test_id fixture
):
    """
    Tests determine_app_restart_actions for various scenarios including
    newly stuck, previously stuck, and unstuck applications.
    """
    caplog.set_level(logging.DEBUG, logger=MODULE_LOGGER_NAME)

    current_stuck_file_paths: Set[Path] = {Path(f) for f in current_stuck_files_str}
    expected_restart_files: Set[Path] = {
        RESTART_DIR / f for f in expected_restart_files_str
    }

    actual_restart_files, actual_current_stuck_apps = determine_app_restart_actions(
        current_stuck_file_paths=current_stuck_file_paths,
        previously_signaled_apps=previously_signaled_apps,
        restart_trigger_directory=RESTART_DIR,
    )

    assert actual_restart_files == expected_restart_files
    assert actual_current_stuck_apps == expected_current_stuck_apps

    if expected_info_log_substr:
        log_entry = find_log_record(caplog, logging.INFO, [expected_info_log_substr])
        assert log_entry is not None, (
            f"[{test_id}] Expected INFO log with '{expected_info_log_substr}' not found. "
            f"Actual INFO logs: {[r.message for r in caplog.records if r.levelno == logging.INFO]}"
        )

    if expected_debug_log_substr:
        relevant_debug_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.DEBUG
            and r.name == MODULE_LOGGER_NAME
            and not r.message.startswith("Determined restart trigger file")
            and not r.message.startswith("Could not extract App Name")
        ]
        found_specific_debug = any(
            expected_debug_log_substr in msg for msg in relevant_debug_messages
        )
        assert found_specific_debug, (
            f"[{test_id}] Expected DEBUG log with '{expected_debug_log_substr}' not found. "
            f"Relevant DEBUG logs from SUT: {relevant_debug_messages}"
        )

    # Explicit checks for warnings from get_app_name_from_path for specific test cases
    if test_id == "edge_invalid_name_mixed":
        assert find_log_record(
            caplog,
            logging.WARNING,
            ["Could not extract App Name", repr("INVALIDFILE.log")],
        ), f"[{test_id}] Expected warning for INVALIDFILE.log"
    elif test_id == "edge_all_invalid_names":
        assert find_log_record(
            caplog,
            logging.WARNING,
            ["Could not extract App Name", repr("INVALIDFILE.log")],
        ), f"[{test_id}] Expected warning for INVALIDFILE.log"
        assert find_log_record(
            caplog, logging.WARNING, ["Could not extract App Name", repr("-ts.pcap")]
        ), f"[{test_id}] Expected warning for -ts.pcap"


def test_determine_app_restart_actions_cycle_simulation(
    caplog: pytest.LogCaptureFixture,
):
    """
    Simulates the state changes across cycles as per FR4 and Example Flow.
    Cycle 1: APP1 becomes stuck -> signal.
    Cycle 2: APP1 unstuck.
    Cycle 3: APP1 becomes stuck again -> signal again.
    """
    caplog.set_level(logging.DEBUG, logger=MODULE_LOGGER_NAME)

    # --- Cycle 1: APP1 becomes stuck ---
    current_stuck_1 = {Path("APP1-ts1.pcap")}
    previous_signaled_1 = set()
    expected_restarts_1 = {RESTART_DIR / "APP1.restart"}
    expected_apps_1 = {"APP1"}

    restarts_1, apps_1 = determine_app_restart_actions(
        current_stuck_file_paths=current_stuck_1,
        previously_signaled_apps=previous_signaled_1,
        restart_trigger_directory=RESTART_DIR,
    )
    assert restarts_1 == expected_restarts_1
    assert apps_1 == expected_apps_1
    assert find_log_record(
        caplog,
        logging.INFO,
        ["Newly stuck applications identified for restart signal: APP1"],
    )

    # --- Cycle 2: APP1 unstuck ---
    # `apps_1` becomes the `previously_signaled_apps` for the next cycle.
    current_stuck_2 = set()
    previous_signaled_2 = apps_1  # This is {"APP1"}
    expected_restarts_2 = set()
    expected_apps_2 = set()

    caplog.clear()  # Clear logs for the next cycle check
    restarts_2, apps_2 = determine_app_restart_actions(
        current_stuck_file_paths=current_stuck_2,
        previously_signaled_apps=previous_signaled_2,
        restart_trigger_directory=RESTART_DIR,
    )
    assert restarts_2 == expected_restarts_2
    assert apps_2 == expected_apps_2
    assert find_log_record(caplog, logging.DEBUG, ["No applications currently stuck."])

    # --- Cycle 3: APP1 becomes stuck again ---
    # `apps_2` becomes the `previously_signaled_apps` for the next cycle.
    current_stuck_3 = {Path("APP1-ts2.pcap")}  # New timestamp, same app
    previous_signaled_3 = apps_2  # This is set()
    expected_restarts_3 = {RESTART_DIR / "APP1.restart"}
    expected_apps_3 = {"APP1"}

    caplog.clear()  # Clear logs for the next cycle check
    restarts_3, apps_3 = determine_app_restart_actions(
        current_stuck_file_paths=current_stuck_3,
        previously_signaled_apps=previous_signaled_3,
        restart_trigger_directory=RESTART_DIR,
    )
    assert restarts_3 == expected_restarts_3
    assert apps_3 == expected_apps_3
    assert find_log_record(
        caplog,
        logging.INFO,
        ["Newly stuck applications identified for restart signal: APP1"],
    )
