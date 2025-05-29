from typing import Optional, Tuple

import pytest
import logging
import stat

from pathlib import Path
from unittest.mock import Mock

# Import SUT
from datamover.file_functions.safe_stat import safe_stat

# Import global test utilities
from tests.test_utils.fs_helpers import create_mock_stat_attrs
from tests.test_utils.logging_helpers import find_log_record


# --- Test Cases ---


def test_safe_stat_success_regular_file(mock_fs: Mock):
    """Verify safe_stat returns (inode, size) for a regular file."""
    test_path = Path("/path/to/regular_file.dat")
    expected_inode = 54321
    expected_size = 5000

    mock_stat_res = create_mock_stat_attrs(
        st_mode=stat.S_IFREG | 0o644,
        st_ino=expected_inode,
        st_size=expected_size,
    )
    mock_fs.lstat.return_value = mock_stat_res

    result: Optional[Tuple[int, int]] = safe_stat(test_path, fs=mock_fs)

    assert result == (expected_inode, expected_size)
    mock_fs.lstat.assert_called_once_with(test_path)


def test_safe_stat_fails_directory(mock_fs: Mock, caplog: pytest.LogCaptureFixture):
    """Verify safe_stat returns None for a directory."""
    test_path = Path("/path/to/directory")
    mock_stat_res = create_mock_stat_attrs(st_mode=stat.S_IFDIR | 0o755)
    mock_fs.lstat.return_value = mock_stat_res

    caplog.set_level(logging.DEBUG)
    result: Optional[Tuple[int, int]] = safe_stat(test_path, fs=mock_fs)

    assert result is None
    mock_fs.lstat.assert_called_once_with(test_path)

    log_entry = find_log_record(
        caplog, logging.DEBUG, [str(test_path), "Path is not a regular file"]
    )
    assert log_entry is not None


def test_safe_stat_fails_symlink(mock_fs: Mock, caplog: pytest.LogCaptureFixture):
    """Verify safe_stat returns None for a symbolic link."""
    test_path = Path("/path/to/symlink")
    mock_stat_res = create_mock_stat_attrs(st_mode=stat.S_IFLNK | 0o777)
    mock_fs.lstat.return_value = mock_stat_res

    caplog.set_level(logging.DEBUG)
    result = safe_stat(test_path, fs=mock_fs)

    assert result is None
    mock_fs.lstat.assert_called_once_with(test_path)
    log_entry = find_log_record(
        caplog, logging.DEBUG, [str(test_path), "Path is not a regular file"]
    )
    assert log_entry is not None


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError, OSError])
def test_safe_stat_fails_os_error(
    mock_fs: Mock, caplog: pytest.LogCaptureFixture, error_type: type[OSError]
):
    """Verify safe_stat returns None when lstat raises common OSErrors."""
    test_path = Path("/path/to/error_file")
    error_instance: OSError = error_type(f"Mock {error_type.__name__} for {test_path}")
    mock_fs.lstat.side_effect = error_instance

    caplog.set_level(logging.INFO)
    result: Optional[Tuple[int, int]] = safe_stat(test_path, fs=mock_fs)

    assert result is None
    mock_fs.lstat.assert_called_once_with(test_path)

    expected_substrings = [str(test_path)]
    if isinstance(error_instance, FileNotFoundError):
        expected_substrings.append("File not found")
    else:
        expected_substrings.append("failed for")
        expected_substrings.append(str(error_instance))  # Or a part of it if too long

    log_entry = find_log_record(caplog, logging.INFO, expected_substrings)
    assert log_entry is not None


def test_safe_stat_fails_unexpected_error(
    mock_fs: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify safe_stat returns None when lstat raises an unexpected Exception."""
    test_path = Path("/path/to/unexpected")
    unexpected_err = ValueError("Something weird happened")
    mock_fs.lstat.side_effect = unexpected_err

    caplog.set_level(logging.ERROR)
    result = safe_stat(test_path, fs=mock_fs)

    assert result is None
    mock_fs.lstat.assert_called_once_with(test_path)

    log_entry = find_log_record(
        caplog, logging.ERROR, [str(test_path), "Unexpected error"]
    )
    assert log_entry is not None

    # Unpack the exc_info tuple instead of indexing to satisfy mypy
    assert log_entry.exc_info is not None
    exc_type, exc_val, exc_tb = log_entry.exc_info

    assert exc_type is ValueError
    assert exc_val is unexpected_err

    # Verify the original error message appears in the logged traceback text
    assert log_entry.exc_text is not None
    assert str(unexpected_err) in log_entry.exc_text
