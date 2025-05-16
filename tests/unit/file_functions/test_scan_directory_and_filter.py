import logging
from pathlib import Path
from typing import Optional

import pytest
from unittest.mock import Mock

# Import SUT and related types
from datamover.file_functions.scan_directory_and_filter import (
    scan_directory_and_filter,
)
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.file_functions.file_exceptions import ScanDirectoryError

# Import test helpers
from tests.test_utils.logging_helpers import find_log_record

# Target to patch gather_file_data (consistent with co-worker's good practice)
GATHER_PATCH_TARGET = (
    "datamover.file_functions.scan_directory_and_filter.gather_file_data"
)

# --- Fixtures specific to this test file ---


@pytest.fixture
def all_sample_entries() -> list[GatheredEntryData]:
    """
    Provides a diverse list of GatheredEntryData entries for filtering tests.
    Order is important for some assertions.
    """
    return [
        GatheredEntryData(
            mtime=1.0, size=10, path=Path("/scan/data/file1.csv")
        ),  # Index 0
        GatheredEntryData(
            mtime=2.0, size=20, path=Path("/scan/data/file2.CSV")
        ),  # Index 1
        GatheredEntryData(
            mtime=3.0, size=30, path=Path("/scan/data/notes.txt")
        ),  # Index 2
        GatheredEntryData(
            mtime=4.0, size=40, path=Path("/scan/data/archive")
        ),  # Index 3 (no dot)
        GatheredEntryData(
            mtime=5.0, size=50, path=Path("/scan/data/image.jpg")
        ),  # Index 4
    ]


@pytest.fixture
def non_matching_sample_entries() -> list[GatheredEntryData]:
    """Provides a list of entries that won't match common test extensions like 'csv' or 'pdf'."""
    return [
        GatheredEntryData(mtime=3.0, size=30, path=Path("/scan/data/notes.txt")),
        GatheredEntryData(
            mtime=4.0, size=40, path=Path("/scan/data/archive")
        ),  # No dot
        GatheredEntryData(mtime=5.0, size=50, path=Path("/scan/data/image.jpg")),
    ]


@pytest.fixture
def mock_scan_directory() -> Path:
    """A common directory path passed to the scan function for these tests."""
    return Path("/scan/data")


# --- Test Cases ---


def test_filters_correctly_with_case_insensitive_behavior(
    mocker,
    caplog: pytest.LogCaptureFixture,
    all_sample_entries: list[GatheredEntryData],
    mock_scan_directory: Path,
    mock_fs: Mock,  # Injected from conftest.py
):
    """
    Tests correct filtering:
    - Handles case-insensitive input for 'extension_no_dot'.
    - Matches file suffixes case-insensitively.
    - Preserves order of matched entries.
    - Logs a debug message with correct counts.
    """
    # Arrange
    mock_gather = mocker.patch(GATHER_PATCH_TARGET, return_value=all_sample_entries)
    caplog.set_level(logging.DEBUG)
    input_extension_mixed_case = "CsV"  # SUT should lowercase this to 'csv'

    # Act
    result = scan_directory_and_filter(
        directory=mock_scan_directory,
        fs=mock_fs,
        extension_no_dot=input_extension_mixed_case,
    )

    # Assert
    # Expected: only the two CSV entries, in their original order from all_sample_entries
    expected_filtered_entries = [all_sample_entries[0], all_sample_entries[1]]
    assert result == expected_filtered_entries, "Filtered list or order is incorrect"

    mock_gather.assert_called_once_with(directory=mock_scan_directory, fs=mock_fs)

    # Log assertion: SUT converts input extension to lowercase for the log's suffix
    log_entry = find_log_record(
        caplog,
        logging.DEBUG,
        [
            f"Filtered {len(all_sample_entries)} gathered entries",
            f"down to {len(expected_filtered_entries)}",
            "matching suffix '.csv'",  # SUT logs the lowercased, dotted suffix
        ],
    )
    assert log_entry is not None, (
        "Expected debug log of filtering counts not found or incorrect"
    )


@pytest.mark.parametrize(
    "gather_return_value_fixture, input_extension, description_id",
    [
        ("non_matching_sample_entries", "pdf", "no_matches_from_non_empty_gather"),
        (
            None,
            "txt",
            "empty_gather_results",
        ),  # Using None as a marker for an empty list
    ],
    ids=lambda val: val
    if isinstance(val, str)
    else "",  # Use description_id for pytest -k
)
def test_returns_empty_list_scenarios(
    mocker,
    caplog: pytest.LogCaptureFixture,
    mock_scan_directory: Path,
    mock_fs: Mock,  # Injected from conftest.py
    gather_return_value_fixture: Optional[str],  # Fixture name as string, or None
    input_extension: str,
    description_id: str,
    request,  # Pytest request fixture to dynamically get other fixtures
):
    """
    Tests that an empty list is returned and logged correctly when:
    1. `gather_file_data` returns entries, but none match the extension.
    2. `gather_file_data` itself returns an empty list.
    """
    # Arrange
    # Dynamically get fixture value if name is provided, else use empty list
    actual_gather_return_value: list[GatheredEntryData] = []
    if gather_return_value_fixture:
        actual_gather_return_value = request.getfixturevalue(
            gather_return_value_fixture
        )

    mock_gather = mocker.patch(
        GATHER_PATCH_TARGET, return_value=actual_gather_return_value
    )
    caplog.set_level(logging.DEBUG)

    # Act
    result = scan_directory_and_filter(
        directory=mock_scan_directory,
        fs=mock_fs,
        extension_no_dot=input_extension,
    )

    # Assert
    assert result == [], (
        f"Result should be an empty list for scenario: {description_id}"
    )
    mock_gather.assert_called_once_with(directory=mock_scan_directory, fs=mock_fs)

    expected_log_suffix = f".{input_extension.lower()}"
    initial_count = len(actual_gather_return_value)

    log_entry = find_log_record(
        caplog,
        logging.DEBUG,
        [
            f"Filtered {initial_count} gathered entries",
            "down to 0",  # Result count is always 0 for these scenarios
            f"matching suffix '{expected_log_suffix}'",
        ],
    )
    assert log_entry is not None, (
        f"Debug log for scenario '{description_id}' not found or incorrect"
    )


def test_propagates_scan_directory_error(
    mocker,
    mock_scan_directory: Path,  # Use the fixture
    mock_fs: Mock,  # Injected from conftest.py
):
    """
    If gather_file_data raises ScanDirectoryError, it propagates unchanged.
    """
    # Arrange
    original_os_error = PermissionError("Permission denied for test")
    scan_error = ScanDirectoryError(
        message="Simulated gather failure",
        directory=mock_scan_directory,
        original_exception=original_os_error,
    )
    # Assign the created mock to a variable
    mocked_gather_function = mocker.patch(GATHER_PATCH_TARGET, side_effect=scan_error)

    # Act & Assert
    with pytest.raises(ScanDirectoryError) as excinfo:
        scan_directory_and_filter(
            directory=mock_scan_directory,
            fs=mock_fs,
            extension_no_dot="log",
        )

    assert excinfo.type is ScanDirectoryError
    assert excinfo.value is scan_error  # Check it's the exact instance
    assert excinfo.value.directory == mock_scan_directory
    assert excinfo.value.original_exception is original_os_error
    assert (
        str(excinfo.value)
        == f"Simulated gather failure [Directory: {mock_scan_directory}]"
    )

    # Verify the dependency was still called using the variable that holds the mock
    mocked_gather_function.assert_called_once_with(
        directory=mock_scan_directory, fs=mock_fs
    )
