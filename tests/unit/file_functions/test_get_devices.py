from pathlib import Path
from unittest.mock import Mock

import pytest

# System Under Test (SUT) - adjust paths if necessary
from datamover.file_functions.get_devices import get_device
from datamover.startup_code.load_config import ConfigError

# Global test utilities
from tests.test_utils.fs_helpers import create_mock_stat_attrs

# --- Test Cases ---


def test_get_device_success(mock_fs: Mock):
    """Test get_device returns correct st_dev on success using injected FS."""
    test_path = Path("/path/to/some/file.txt")
    expected_dev_id = 99

    # Use the global helper from fs_helpers.py
    # Only st_dev is critical for this test; other attributes get defaults.
    mock_stat_obj = create_mock_stat_attrs(st_dev=expected_dev_id)
    mock_fs.stat.return_value = mock_stat_obj

    result = get_device(test_path, fs=mock_fs)

    assert result == expected_dev_id
    mock_fs.stat.assert_called_once_with(test_path)


def test_get_device_file_not_found_raises_config_error(mock_fs: Mock):
    """Test get_device raises ConfigError on FileNotFoundError from fs.stat."""
    test_path = Path("/path/to/nonexistent/file.txt")
    original_exception = FileNotFoundError(f"No such file or directory: '{test_path}'")
    mock_fs.stat.side_effect = original_exception

    # Ensure this error message format matches what get_device actually produces
    expected_error_msg = f"[Directories] cannot stat {test_path}"
    with pytest.raises(ConfigError) as excinfo:
        get_device(test_path, fs=mock_fs)

    assert str(excinfo.value) == expected_error_msg
    assert (
        excinfo.value.__cause__ is original_exception
    )  # Check for proper exception chaining
    mock_fs.stat.assert_called_once_with(test_path)


def test_get_device_permission_error_propagates(mock_fs: Mock):
    """Test get_device allows PermissionError from fs.stat to propagate directly."""
    test_path = Path("/path/to/restricted/file.txt")
    original_exception = PermissionError(f"Permission denied: '{test_path}'")
    mock_fs.stat.side_effect = original_exception

    with pytest.raises(PermissionError) as excinfo:
        get_device(test_path, fs=mock_fs)

    assert (
        excinfo.value is original_exception
    )  # Ensure the original exception instance is propagated
    mock_fs.stat.assert_called_once_with(test_path)
