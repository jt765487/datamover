import logging
import os
import stat
from pathlib import Path
from unittest.mock import Mock

import pytest

# Import SUT
from datamover.file_functions.validate_file import validate_file

# Import global test utilities
from tests.test_utils.fs_helpers import create_mock_stat_attrs
from tests.test_utils.logging_helpers import find_log_record

# --- Fixtures specific to this test file ---


@pytest.fixture
def source_input_path() -> Path:
    """Input path to validate. Corresponds to a file within expected_dir."""
    return Path("/expected/dir/source_file.txt")


@pytest.fixture
def expected_dir() -> Path:
    """Expected parent directory (assumed to be resolved for test purposes)."""
    return Path("/expected/dir")


# --- Test Cases ---


def test_validate_file_success(
    mock_fs: Mock,  # Injected from conftest.py
    source_input_path: Path,
    expected_dir: Path,
):
    """Test successful validation returns resolved path using mock_fs."""
    # Arrange
    # Define the path that fs.resolve should return for this success case.
    # It should be the source_input_path's name within the expected_dir.
    resolved_path_mock = expected_dir / source_input_path.name

    # Configure mock_fs methods for the success path:
    # 1. fs.lstat (called by safe_stat) should return stats for a regular file.
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=stat.S_IFREG | 0o644)
    # 2. fs.resolve should return our defined resolved_path_mock.
    mock_fs.resolve.return_value = resolved_path_mock
    # 3. fs.access should indicate the file is readable.
    mock_fs.access.return_value = True

    # Act
    result = validate_file(source_input_path, expected_dir, fs=mock_fs)

    # Assert
    assert result == resolved_path_mock, "Should return the resolved path on success."
    mock_fs.lstat.assert_called_once_with(source_input_path)
    mock_fs.resolve.assert_called_once_with(source_input_path, strict=True)
    mock_fs.access.assert_called_once_with(resolved_path_mock, os.R_OK)


def test_validate_file_fail_safe_stat_lstat_error(
    mock_fs: Mock,
    source_input_path: Path,
    expected_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Test returns None if safe_stat fails due to fs.lstat raising an error."""
    # Arrange
    # Configure fs.lstat to raise an error, simulating a failure within safe_stat.
    mock_fs.lstat.side_effect = FileNotFoundError("Mock Lstat failed for test")
    caplog.set_level(logging.ERROR)  # SUT logs ERROR for safe_stat failure

    # Act
    result = validate_file(source_input_path, expected_dir, fs=mock_fs)

    # Assert
    assert result is None, "Should return None when safe_stat (lstat) fails."
    mock_fs.lstat.assert_called_once_with(source_input_path)
    # Check for the specific log message from validate_file when safe_stat fails.
    log_entry = find_log_record(
        caplog,
        logging.ERROR,
        ["Initial checks via safe_stat failed", str(source_input_path)],
    )
    assert log_entry is not None, "Error log for safe_stat failure not found."
    # Ensure subsequent fs methods are not called.
    mock_fs.resolve.assert_not_called()
    mock_fs.access.assert_not_called()


def test_validate_file_fail_safe_stat_not_regular_file(
    mock_fs: Mock,
    source_input_path: Path,
    expected_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Test returns None if safe_stat fails because path is not a regular file (e.g., a directory)."""
    # Arrange
    # Configure fs.lstat to return stats for a directory, causing safe_stat to return None.
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=stat.S_IFDIR | 0o755)
    caplog.set_level(logging.ERROR)  # SUT logs ERROR for safe_stat failure

    # Act
    result = validate_file(source_input_path, expected_dir, fs=mock_fs)

    # Assert
    assert result is None, "Should return None when file is not regular."
    mock_fs.lstat.assert_called_once_with(source_input_path)
    log_entry = find_log_record(
        caplog,
        logging.ERROR,
        ["Initial checks via safe_stat failed", str(source_input_path)],
    )
    assert log_entry is not None, (
        "Error log for non-regular file via safe_stat not found."
    )
    mock_fs.resolve.assert_not_called()
    mock_fs.access.assert_not_called()


def test_validate_file_fail_resolve_raises_file_not_found(
    mock_fs: Mock,
    source_input_path: Path,
    expected_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Test returns None if fs.resolve(strict=True) raises FileNotFoundError."""
    # Arrange
    # fs.lstat (for safe_stat) passes.
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=stat.S_IFREG | 0o644)
    # fs.resolve fails.
    resolve_error = FileNotFoundError("Mock vanished during resolve")
    mock_fs.resolve.side_effect = resolve_error
    caplog.set_level(logging.WARNING)  # SUT logs WARNING for this specific failure.

    # Act
    result = validate_file(source_input_path, expected_dir, fs=mock_fs)

    # Assert
    assert result is None, (
        "Should return None when fs.resolve raises FileNotFoundError."
    )
    mock_fs.lstat.assert_called_once_with(source_input_path)
    mock_fs.resolve.assert_called_once_with(source_input_path, strict=True)
    mock_fs.access.assert_not_called()
    log_entry = find_log_record(
        caplog,
        logging.WARNING,
        [
            "File not found during resolve/access check",
            str(source_input_path),
            str(resolve_error),
        ],
    )
    assert log_entry is not None, "Warning log for resolve FileNotFoundError not found."


def test_validate_file_fail_confinement_check(
    mock_fs: Mock,
    source_input_path: Path,
    expected_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Test returns None if resolved path's parent does not match expected_dir."""
    # Arrange
    # fs.lstat (for safe_stat) passes.
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=stat.S_IFREG | 0o644)
    # fs.resolve returns a path that is *not* within the expected_dir.
    # Note: source_input_path.name is 'source_file.txt'
    wrong_resolved_path = Path("/some/other/resolved_dir") / source_input_path.name
    mock_fs.resolve.return_value = wrong_resolved_path
    caplog.set_level(logging.ERROR)  # SUT logs ERROR for confinement failure.

    # Act
    result = validate_file(source_input_path, expected_dir, fs=mock_fs)

    # Assert
    assert result is None, "Should return None on confinement failure."
    mock_fs.lstat.assert_called_once_with(source_input_path)
    mock_fs.resolve.assert_called_once_with(source_input_path, strict=True)
    mock_fs.access.assert_not_called()  # Access check should be skipped.
    log_entry = find_log_record(
        caplog,
        logging.ERROR,
        [
            "not directly within expected directory",
            str(wrong_resolved_path),
            str(expected_dir),
        ],
    )
    assert log_entry is not None, "Error log for confinement failure not found."


def test_validate_file_fail_not_readable_via_access(
    mock_fs: Mock,
    source_input_path: Path,
    expected_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Test returns None if fs.access check returns False (not readable)."""
    # Arrange
    resolved_path_mock = expected_dir / source_input_path.name
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=stat.S_IFREG | 0o644)
    mock_fs.resolve.return_value = resolved_path_mock
    # fs.access indicates the file is not readable.
    mock_fs.access.return_value = False
    caplog.set_level(logging.ERROR)  # SUT logs ERROR for readability failure.

    # Act
    result = validate_file(source_input_path, expected_dir, fs=mock_fs)

    # Assert
    assert result is None, "Should return None when file is not readable."
    mock_fs.lstat.assert_called_once_with(source_input_path)
    mock_fs.resolve.assert_called_once_with(source_input_path, strict=True)
    mock_fs.access.assert_called_once_with(resolved_path_mock, os.R_OK)
    log_entry = find_log_record(
        caplog,
        logging.ERROR,
        ["Source path", str(resolved_path_mock), "is not readable"],
    )
    assert log_entry is not None, "Error log for non-readable file not found."


@pytest.mark.parametrize(
    "fs_method_to_fail, error_to_raise, expected_log_level, expected_log_substring",
    [
        (
            "resolve",
            OSError("Mock OS error during resolve"),
            logging.ERROR,
            "OS error during resolve or access check",
        ),
        (
            "access",
            OSError("Mock OS error during access"),
            logging.ERROR,
            "OS error during resolve or access check",
        ),
        (
            "resolve",
            Exception("Mock unexpected resolve error"),
            logging.ERROR,
            "Unexpected error during resolve/access check",
        ),
        (
            "access",
            Exception("Mock unexpected access error"),
            logging.ERROR,
            "Unexpected error during resolve/access check",
        ),
    ],
    ids=[
        "resolve_os_error",
        "access_os_error",
        "resolve_unexpected_error",
        "access_unexpected_error",
    ],
)
def test_validate_file_fail_fs_method_raises_error(
    mock_fs: Mock,
    source_input_path: Path,
    expected_dir: Path,
    caplog: pytest.LogCaptureFixture,
    fs_method_to_fail: str,
    error_to_raise: Exception,
    expected_log_level: int,
    expected_log_substring: str,
):
    """
    Tests returns None if fs.resolve or fs.access raises OSError or other unexpected Exception.
    """
    # Arrange
    resolved_path_mock = expected_dir / source_input_path.name
    # fs.lstat (for safe_stat) always passes for these scenarios.
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=stat.S_IFREG | 0o644)
    caplog.set_level(expected_log_level)

    if fs_method_to_fail == "resolve":
        mock_fs.resolve.side_effect = error_to_raise
        # access should not be called if resolve fails
        mock_fs.access.return_value = True  # Default for completeness
    elif fs_method_to_fail == "access":
        mock_fs.resolve.return_value = resolved_path_mock  # Resolve must pass
        mock_fs.access.side_effect = error_to_raise

    # Act
    result = validate_file(source_input_path, expected_dir, fs=mock_fs)

    # Assert
    assert result is None, (
        f"Should return None when {fs_method_to_fail} raises {type(error_to_raise).__name__}."
    )
    mock_fs.lstat.assert_called_once_with(source_input_path)
    mock_fs.resolve.assert_called_once_with(source_input_path, strict=True)

    if fs_method_to_fail == "access":
        mock_fs.access.assert_called_once_with(resolved_path_mock, os.R_OK)
    else:  # resolve failed
        mock_fs.access.assert_not_called()

    log_entry = find_log_record(
        caplog,
        expected_log_level,
        [expected_log_substring, str(source_input_path), str(error_to_raise)],
    )
    assert log_entry is not None, (
        f"Log for {fs_method_to_fail} raising {type(error_to_raise).__name__} not found."
    )
