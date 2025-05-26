import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# --- Test Target ---
from datamover.scanner.scan_reporting import (
    report_newly_lost,
    report_newly_stuck_active,
    report_removed_from_tracking,
    report_state_changes,
)

# --- Test Helper ---
# Assuming find_log_record is in this path, adjust if necessary
from tests.test_utils.logging_helpers import find_log_record

MODULE_LOGGER = "datamover.scanner.scan_reporting"


# --- Fixtures ---


@pytest.fixture
def sample_paths() -> set[Path]:  # Updated type hint
    """Sample set of Path objects for consistent testing."""
    return {
        Path("/test/dir/z_file.dat"),
        Path("/test/dir/a_file.log"),
        Path("/test/dir/middle.txt"),
    }


@pytest.fixture
def sorted_path_strings(sample_paths: set[Path]) -> list[str]:  # Updated type hint
    """Expected sorted list of POSIX path strings from sample_paths."""
    return sorted(p.as_posix() for p in sample_paths)


# --- Parametrized Tests for Warning Logs (report_newly_lost, report_newly_stuck_active) ---


@pytest.mark.parametrize(
    "report_function_to_test, timeout_value, log_message_prefix_substring",
    [
        (report_newly_lost, 30.5, "Newly detected LOST files (unmodified >"),
        (
            report_newly_stuck_active,
            60.2,
            "Newly detected STUCK ACTIVE files (active & present >",
        ),
    ],
    ids=["report_lost", "report_stuck_active"],
)
def test_warning_logged_when_files_present(
    caplog: pytest.LogCaptureFixture,
    report_function_to_test,  # The actual function to test
    timeout_value: float,
    log_message_prefix_substring: str,
    sample_paths: set[Path],  # Updated type hint
    sorted_path_strings: list[str],  # Updated type hint
):
    """Tests that a WARNING log is generated with correct details when file paths are provided."""
    caplog.set_level(logging.WARNING, logger=MODULE_LOGGER)

    # Act
    result = report_function_to_test(file_paths=sample_paths, timeout=timeout_value)
    assert result is None, "Reporting functions should return None."

    # Assert log using find_log_record
    # The SUT formats timeout with "%.1f sec" and logs the list of paths.
    # repr(sorted_path_strings) will give a string like "['/path/a', '/path/b']"
    expected_substrings = [
        log_message_prefix_substring,
        f"{timeout_value:.1f} sec",  # Match the SUT's formatting
        repr(sorted_path_strings),  # Match how a list of strings is logged via %s
    ]
    log_entry = find_log_record(caplog, logging.WARNING, expected_substrings)
    assert log_entry is not None, "Expected WARNING log message not found or incorrect."
    # Optional: Further check args if find_log_record doesn't suffice, but it should for formatted msg
    # assert log_entry.args[0] == pytest.approx(timeout_value)
    # assert log_entry.args[1] == sorted_path_strings


@pytest.mark.parametrize(
    "report_function_to_test, timeout_value",
    [
        (report_newly_lost, 30.0),
        (report_newly_stuck_active, 60.0),
    ],
    ids=["report_lost_no_files", "report_stuck_active_no_files"],
)
def test_no_warning_log_when_no_files(
    caplog: pytest.LogCaptureFixture, report_function_to_test, timeout_value: float
):
    """Tests that no WARNING log is generated if the file_paths set is empty."""
    caplog.set_level(logging.WARNING, logger=MODULE_LOGGER)

    # Act
    result = report_function_to_test(file_paths=set(), timeout=timeout_value)
    assert result is None

    # Assert no logs were generated
    assert not caplog.records, (
        "No log records should be generated when file_paths is empty."
    )


# --- Tests for Info Logs (report_removed_from_tracking) ---


def test_info_logged_for_removed_files(
    caplog: pytest.LogCaptureFixture,
    sample_paths: set[Path],  # Updated type hint
    sorted_path_strings: list[str],  # Updated type hint
):
    """Tests that an INFO log is generated with correct details for removed files."""
    caplog.set_level(logging.INFO, logger=MODULE_LOGGER)

    # Act
    result = report_removed_from_tracking(file_paths=sample_paths)
    assert result is None

    # Assert log using find_log_record
    expected_substrings = [
        "Files REMOVED from tracking (previously tracked, now missing from scan):",
        repr(sorted_path_strings),  # Match how a list of strings is logged via %s
    ]
    log_entry = find_log_record(caplog, logging.INFO, expected_substrings)
    assert log_entry is not None, (
        "Expected INFO log for removed files not found or incorrect."
    )
    # Optional: Further check args if needed
    # assert log_entry.args[0] == sorted_path_strings


def test_no_info_log_when_no_removed_files(caplog: pytest.LogCaptureFixture):
    """Tests that no INFO log is generated if the removed_file_paths set is empty."""
    caplog.set_level(logging.INFO, logger=MODULE_LOGGER)

    # Act
    result = report_removed_from_tracking(file_paths=set())
    assert result is None

    # Assert no logs were generated
    assert not caplog.records, (
        "No log records should be generated for removed files when set is empty."
    )


# --- Tests for the Orchestrator Function (report_state_changes) ---

MODULE_PATH_FOR_PATCHING = (
    "datamover.scanner.scan_reporting"  # Path for patching helpers
)


class TestReportStateChanges:
    @pytest.fixture
    def mock_report_lost(self, mocker) -> MagicMock:  # Removed MockerFixture
        return mocker.patch(
            f"{MODULE_PATH_FOR_PATCHING}.report_newly_lost", autospec=True
        )

    @pytest.fixture
    def mock_report_stuck(self, mocker) -> MagicMock:  # Removed MockerFixture
        return mocker.patch(
            f"{MODULE_PATH_FOR_PATCHING}.report_newly_stuck_active", autospec=True
        )

    @pytest.fixture
    def mock_report_removed(self, mocker) -> MagicMock:  # Removed MockerFixture
        return mocker.patch(
            f"{MODULE_PATH_FOR_PATCHING}.report_removed_from_tracking", autospec=True
        )

    def test_calls_helpers_with_correct_args(  # Simplified name, order is implicit
        self,
        mock_report_lost: MagicMock,
        mock_report_stuck: MagicMock,
        mock_report_removed: MagicMock,
        sample_paths: set[Path],  # Updated type hint
    ):
        """Tests that report_state_changes calls its helper functions with the correct arguments."""
        # Arrange
        lost_paths_set = sample_paths.copy()
        stuck_paths_set = {Path("/other/stuck1"), Path("/other/stuck2")}
        removed_paths_set = {Path("/removed/file")}
        lost_timeout_val = 20.0
        stuck_timeout_val = 40.0

        # Act
        report_state_changes(
            newly_lost_paths=lost_paths_set,
            newly_stuck_active_paths=stuck_paths_set,
            removed_tracking_paths=removed_paths_set,
            lost_timeout=lost_timeout_val,
            stuck_active_timeout=stuck_timeout_val,
        )

        # Assert calls
        mock_report_lost.assert_called_once_with(
            file_paths=lost_paths_set, timeout=lost_timeout_val
        )
        mock_report_stuck.assert_called_once_with(
            file_paths=stuck_paths_set, timeout=stuck_timeout_val
        )
        mock_report_removed.assert_called_once_with(file_paths=removed_paths_set)

    def test_integration_logs_all_types_correctly(
        self,
        caplog: pytest.LogCaptureFixture,
        # No mocks here, testing actual log output of helpers
    ):
        """
        Tests the integrated behavior of report_state_changes, ensuring all types of
        log messages (WARNING for lost/stuck, INFO for removed) are generated correctly.
        """
        caplog.set_level(logging.INFO, logger=MODULE_LOGGER)  # Capture INFO and WARNING

        # Arrange data
        lost_paths = {
            Path("/lost_dir/lost_file1.log"),
            Path("/lost_dir/lost_file0.txt"),
        }
        stuck_paths = {Path("/stuck_dir/stuckB.zip"), Path("/stuck_dir/stuckA.tar")}
        removed_paths = {
            Path("/removed_dir/removedX.dat"),
            Path("/removed_dir/removedW.bak"),
        }

        # Expected sorted string lists for log comparison
        expected_sorted_lost_strs = sorted(p.as_posix() for p in lost_paths)
        expected_sorted_stuck_strs = sorted(p.as_posix() for p in stuck_paths)
        expected_sorted_removed_strs = sorted(p.as_posix() for p in removed_paths)

        lost_timeout_val = 25.3
        stuck_timeout_val = 55.8

        # Act
        report_state_changes(
            newly_lost_paths=lost_paths,
            newly_stuck_active_paths=stuck_paths,
            removed_tracking_paths=removed_paths,
            lost_timeout=lost_timeout_val,
            stuck_active_timeout=stuck_timeout_val,
        )

        # Assert logs using find_log_record
        lost_log = find_log_record(
            caplog,
            logging.WARNING,
            [
                "Newly detected LOST files",
                f"{lost_timeout_val:.1f} sec",
                repr(expected_sorted_lost_strs),
            ],
        )
        assert lost_log is not None, "LOST files warning log not found or incorrect."

        stuck_log = find_log_record(
            caplog,
            logging.WARNING,
            [
                "Newly detected STUCK ACTIVE files",
                f"{stuck_timeout_val:.1f} sec",
                repr(expected_sorted_stuck_strs),
            ],
        )
        assert stuck_log is not None, (
            "STUCK ACTIVE files warning log not found or incorrect."
        )

        removed_log = find_log_record(
            caplog,
            logging.INFO,
            ["Files REMOVED from tracking", repr(expected_sorted_removed_strs)],
        )
        assert removed_log is not None, "REMOVED files info log not found or incorrect."

        # Verify the number of log records to ensure no unexpected logs
        assert len(caplog.records) == 3
