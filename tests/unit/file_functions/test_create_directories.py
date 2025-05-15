import re

import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path

from datamover.file_functions.create_directories import create_directories
from datamover.startup_code.load_config import (
    ConfigError,
)  # Config type hint comes from mock_config

BASE_DIR_PATH = Path("/app/base")
CSV_DIR_PATH = BASE_DIR_PATH / "csv"
DEAD_LETTER_DIR_PATH = BASE_DIR_PATH / "dead_letter"
SOURCE_DIR_PATH = BASE_DIR_PATH / "source"
UPLOADED_DIR_PATH = BASE_DIR_PATH / "uploaded"
WORKER_DIR_PATH = BASE_DIR_PATH / "worker"

ORDERED_OTHER_PATHS = sorted(
    [
        SOURCE_DIR_PATH,
        WORKER_DIR_PATH,
        UPLOADED_DIR_PATH,
        DEAD_LETTER_DIR_PATH,
        CSV_DIR_PATH,
    ]
)

ALL_PATHS_IN_PROCESSING_ORDER = [BASE_DIR_PATH] + ORDERED_OTHER_PATHS


# Device IDs for mocking
DEVICE_ID_BASE = 111
DEVICE_ID_OTHER = 222


@pytest.fixture
def mock_app_config(
    mock_config: MagicMock,
) -> MagicMock:  # mock_config from global conftest
    """Sets up the mock_config with specific paths for these tests."""
    mock_config.base_dir = BASE_DIR_PATH
    mock_config.source_dir = SOURCE_DIR_PATH
    mock_config.worker_dir = WORKER_DIR_PATH
    mock_config.uploaded_dir = UPLOADED_DIR_PATH
    mock_config.dead_letter_dir = DEAD_LETTER_DIR_PATH
    mock_config.csv_dir = CSV_DIR_PATH
    # mock_config.logger_dir = LOG_DIR_PATH # if create_directories ever includes it

    # Ensure all expected attributes are present to avoid AttributeErrors from the test setup itself
    expected_attrs = [
        "base_dir",
        "source_dir",
        "worker_dir",
        "uploaded_dir",
        "dead_letter_dir",
        "csv_dir",
    ]
    for attr in expected_attrs:
        if not hasattr(mock_config, attr) or getattr(mock_config, attr) is None:
            # Assign a MagicMock spec'd as Path if not correctly set by global mock_config
            setattr(mock_config, attr, MagicMock(spec=Path, name=attr))
            # Ensure name attribute is set for Path mocks for easier debugging
            getattr(mock_config, attr).name = Path(f"/mock/{attr}").name
            # Make them actual Path objects for consistency with how function is used
            if attr == "base_dir":
                setattr(mock_config, attr, BASE_DIR_PATH)
            if attr == "source_dir":
                setattr(mock_config, attr, SOURCE_DIR_PATH)
            if attr == "worker_dir":
                setattr(mock_config, attr, WORKER_DIR_PATH)
            if attr == "uploaded_dir":
                setattr(mock_config, attr, UPLOADED_DIR_PATH)
            if attr == "dead_letter_dir":
                setattr(mock_config, attr, DEAD_LETTER_DIR_PATH)
            if attr == "csv_dir":
                setattr(mock_config, attr, CSV_DIR_PATH)

    return mock_config


# --- IMPORTANT: Adjust patch path to where 'get_device' is imported by 'create_directories' ---
PATCH_PATH_GET_DEVICE = "datamover.file_functions.create_directories.get_device"

# --- Happy Paths ---


@patch(PATCH_PATH_GET_DEVICE)
def test_all_dirs_exist_correct_device(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests successful validation when all directories exist and are correct."""
    # Arrange
    mock_fs.exists.return_value = True
    mock_fs.is_dir.return_value = True
    mock_get_device.return_value = DEVICE_ID_BASE

    # Act
    create_directories(mock_app_config, mock_fs)

    # Assert
    expected_get_device_calls = [
        call(p, fs=mock_fs) for p in ALL_PATHS_IN_PROCESSING_ORDER
    ]
    mock_get_device.assert_has_calls(expected_get_device_calls)

    mock_fs.is_dir.assert_any_call(BASE_DIR_PATH)
    for p in ORDERED_OTHER_PATHS:
        mock_fs.exists.assert_any_call(p)
        mock_fs.is_dir.assert_any_call(p)
    mock_fs.mkdir.assert_not_called()


@patch(PATCH_PATH_GET_DEVICE)
def test_base_exists_others_created_correct_device(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests successful creation of other directories when base_dir exists."""
    # Arrange
    mock_fs.exists.side_effect = lambda p: p == BASE_DIR_PATH
    mock_fs.is_dir.return_value = True  # For base_dir
    mock_get_device.return_value = DEVICE_ID_BASE

    # Act
    create_directories(mock_app_config, mock_fs)

    # Assert
    expected_get_device_calls = [
        call(p, fs=mock_fs) for p in ALL_PATHS_IN_PROCESSING_ORDER
    ]
    mock_get_device.assert_has_calls(expected_get_device_calls)

    expected_mkdir_calls = [call(p, exist_ok=True) for p in ORDERED_OTHER_PATHS]
    mock_fs.mkdir.assert_has_calls(expected_mkdir_calls, any_order=False)


# --- Error Paths ---


@patch(PATCH_PATH_GET_DEVICE)  # Still need to patch as it's in the module scope
def test_config_missing_attribute(
    mock_get_device: MagicMock,  # Not used, but needs to be in signature due to patch
    mock_app_config: MagicMock,
    mock_fs: MagicMock,
):
    """Tests ConfigError if a required directory attribute is missing from config."""
    # Arrange
    del mock_app_config.source_dir  # Intentionally remove an attribute

    # Act & Assert
    with pytest.raises(
        ConfigError,
        match="Config object missing required directory attribute: Mock object has no attribute 'source_dir'",
    ):
        create_directories(mock_app_config, mock_fs)


@patch(PATCH_PATH_GET_DEVICE)
def test_base_dir_does_not_exist_via_get_device(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError if base_dir does not exist (get_device signals this)."""
    # Arrange
    get_device_error_msg = f"Path '{BASE_DIR_PATH}' does not exist."

    def side_effect_for_get_device(path, fs):
        if path == BASE_DIR_PATH:
            raise ConfigError(get_device_error_msg)
        return DEVICE_ID_BASE

    mock_get_device.side_effect = side_effect_for_get_device

    # Act & Assert
    with pytest.raises(ConfigError, match=re.escape(get_device_error_msg)):
        create_directories(mock_app_config, mock_fs)

    # Ensure fs.is_dir was not called for BASE_DIR_PATH because get_device failed first
    base_dir_is_dir_called = any(
        c == call(BASE_DIR_PATH) for c in mock_fs.is_dir.call_args_list
    )
    assert not base_dir_is_dir_called, (
        "fs.is_dir(BASE_DIR_PATH) should not be called if get_device for base_dir fails"
    )


@patch(PATCH_PATH_GET_DEVICE)
def test_base_dir_is_not_directory(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError if base_dir exists but is not a directory."""
    # Arrange
    mock_get_device.return_value = DEVICE_ID_BASE  # Simulates base_dir stat-able
    mock_fs.is_dir.side_effect = lambda p: False if p == BASE_DIR_PATH else True

    # Act & Assert
    with pytest.raises(
        ConfigError, match=f"Base path '{BASE_DIR_PATH}' exists but is not a directory."
    ):
        create_directories(mock_app_config, mock_fs)
    mock_fs.is_dir.assert_called_once_with(BASE_DIR_PATH)


@patch(PATCH_PATH_GET_DEVICE)
def test_base_dir_is_dir_os_error(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError wrapping if fs.is_dir(base_dir) raises OSError."""
    # Arrange
    mock_get_device.return_value = DEVICE_ID_BASE
    os_error = OSError("Permission denied for is_dir")

    def side_effect_is_dir(path):  # Changed lambda
        if path == BASE_DIR_PATH:
            raise os_error  # Actually raise
        return True

    mock_fs.is_dir.side_effect = side_effect_is_dir

    # Act & Assert
    with pytest.raises(
        ConfigError,
        match=f"Error validating base directory '{BASE_DIR_PATH}': {os_error}",
    ):
        create_directories(mock_app_config, mock_fs)


@patch(PATCH_PATH_GET_DEVICE)
def test_base_dir_get_device_unexpected_error(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError wrapping for unexpected errors from get_device on base_dir."""
    # Arrange
    unexpected_error = ValueError("Kaboom from get_device")

    def side_effect_get_device(path, fs):  # Changed lambda
        if path == BASE_DIR_PATH:
            raise unexpected_error  # Actually raise
        return DEVICE_ID_BASE

    mock_get_device.side_effect = side_effect_get_device

    # Act & Assert
    with pytest.raises(
        ConfigError,
        match=f"Unexpected error validating base directory '{BASE_DIR_PATH}'",
    ):
        create_directories(mock_app_config, mock_fs)


@patch(PATCH_PATH_GET_DEVICE)
def test_other_dir_exists_as_file(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError if an 'other' directory path exists but is a file."""
    # Arrange
    target_file_path = ORDERED_OTHER_PATHS[0]  # e.g., CSV_DIR_PATH
    mock_get_device.return_value = DEVICE_ID_BASE
    mock_fs.exists.return_value = True
    mock_fs.is_dir.side_effect = lambda p: False if p == target_file_path else True

    # Act & Assert
    with pytest.raises(
        ConfigError,
        match=f"Required path '{target_file_path}' exists but is not a directory.",
    ):
        create_directories(mock_app_config, mock_fs)
    # Ensure it checked base dir correctly first
    mock_get_device.assert_any_call(BASE_DIR_PATH, fs=mock_fs)
    mock_fs.is_dir.assert_any_call(BASE_DIR_PATH)
    # Then failed on the target_file_path
    mock_fs.exists.assert_any_call(target_file_path)
    mock_fs.is_dir.assert_any_call(target_file_path)
    mock_fs.mkdir.assert_not_called()


@patch(PATCH_PATH_GET_DEVICE)
def test_other_dir_mkdir_fails_os_error(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError wrapping if fs.mkdir fails for an 'other' directory."""
    # Arrange
    target_mkdir_fail_path = ORDERED_OTHER_PATHS[0]
    mock_get_device.return_value = DEVICE_ID_BASE
    mock_fs.exists.side_effect = lambda p: p == BASE_DIR_PATH  # Only base exists
    mock_fs.is_dir.return_value = True  # For base_dir

    os_error = OSError("Cannot create directory")

    def side_effect_mkdir(path, exist_ok):  # Changed lambda
        if path == target_mkdir_fail_path:  # target_mkdir_fail_path defined in test
            raise os_error  # Actually raise
        # return None # No need to return for successful mkdir

    mock_fs.mkdir.side_effect = side_effect_mkdir

    # Act & Assert
    with pytest.raises(
        ConfigError,
        match=f"Error accessing or processing path '{target_mkdir_fail_path}': {os_error}",
    ):
        create_directories(mock_app_config, mock_fs)
    mock_fs.mkdir.assert_called_once_with(target_mkdir_fail_path, exist_ok=True)


@patch(PATCH_PATH_GET_DEVICE)
def test_other_dir_different_device(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError if an 'other' directory is on a different device."""
    # Arrange
    target_diff_device_path = ORDERED_OTHER_PATHS[0]
    mock_fs.exists.return_value = True
    mock_fs.is_dir.return_value = True

    def get_device_side_effect(path, fs):
        if path == target_diff_device_path:
            return DEVICE_ID_OTHER
        return DEVICE_ID_BASE

    mock_get_device.side_effect = get_device_side_effect

    # Act & Assert
    expected_msg_literal = (
        f"Directory '{target_diff_device_path}' (device {DEVICE_ID_OTHER}) is not on the same "
        f"filesystem as base directory '{BASE_DIR_PATH}' (device {DEVICE_ID_BASE})."
    )
    # Act & Assert
    with pytest.raises(ConfigError, match=re.escape(expected_msg_literal)):
        create_directories(mock_app_config, mock_fs)


@patch(PATCH_PATH_GET_DEVICE)
def test_other_dir_fs_exists_os_error(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError wrapping if fs.exists raises OSError for an 'other' directory."""
    # Arrange
    target_path = ORDERED_OTHER_PATHS[0]
    mock_get_device.return_value = DEVICE_ID_BASE  # Base dir is fine
    mock_fs.is_dir.return_value = True  # Base dir is fine

    os_error = OSError("fs.exists failed")

    def fs_exists_side_effect(path):
        if path == BASE_DIR_PATH:
            return True
        if path == target_path:
            raise os_error
        return False  # Other non-base paths don't exist

    mock_fs.exists.side_effect = fs_exists_side_effect

    # Act & Assert
    with pytest.raises(
        ConfigError,
        match=f"Error accessing or processing path '{target_path}': {os_error}",
    ):
        create_directories(mock_app_config, mock_fs)


@patch(PATCH_PATH_GET_DEVICE)
def test_other_dir_fs_is_dir_os_error(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError wrapping if fs.is_dir raises OSError for an 'other' directory that exists."""
    # Arrange
    target_path = ORDERED_OTHER_PATHS[0]
    mock_get_device.return_value = DEVICE_ID_BASE
    mock_fs.exists.return_value = True  # All paths "exist"

    os_error = OSError("fs.is_dir failed")

    def fs_is_dir_side_effect(path):
        if path == BASE_DIR_PATH:
            return True
        if path == target_path:
            raise os_error
        return True

    mock_fs.is_dir.side_effect = fs_is_dir_side_effect

    # Act & Assert
    with pytest.raises(
        ConfigError,
        match=f"Error accessing or processing path '{target_path}': {os_error}",
    ):
        create_directories(mock_app_config, mock_fs)


@patch(PATCH_PATH_GET_DEVICE)
def test_other_dir_get_device_config_error(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError re-raising if get_device raises ConfigError for an 'other' directory."""
    # Arrange
    target_path = ORDERED_OTHER_PATHS[0]
    mock_fs.exists.return_value = True
    mock_fs.is_dir.return_value = True

    original_config_error = ConfigError("get_device failed for other")

    def get_device_side_effect(path, fs):
        if path == BASE_DIR_PATH:
            return DEVICE_ID_BASE
        if path == target_path:
            raise original_config_error
        return DEVICE_ID_BASE

    mock_get_device.side_effect = get_device_side_effect

    # Act & Assert
    with pytest.raises(ConfigError, match=str(original_config_error)):
        create_directories(mock_app_config, mock_fs)


@patch(PATCH_PATH_GET_DEVICE)
def test_other_dir_get_device_unexpected_error(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests ConfigError wrapping for unexpected errors from get_device on 'other' directory."""
    # Arrange
    target_path = ORDERED_OTHER_PATHS[0]
    mock_fs.exists.return_value = True
    mock_fs.is_dir.return_value = True

    unexpected_error = EOFError("get_device unexpected EOF")

    def get_device_side_effect(path, fs):
        if path == BASE_DIR_PATH:
            return DEVICE_ID_BASE
        if path == target_path:
            raise unexpected_error
        return DEVICE_ID_BASE

    mock_get_device.side_effect = get_device_side_effect

    # Act & Assert
    with pytest.raises(
        ConfigError, match=f"Unexpected error processing path '{target_path}'"
    ):
        create_directories(mock_app_config, mock_fs)


@patch(PATCH_PATH_GET_DEVICE)
def test_fs_type_error_is_wrapped(
    mock_get_device: MagicMock, mock_app_config: MagicMock, mock_fs: MagicMock
):
    """Tests that TypeError from an fs call is wrapped in ConfigError."""
    # Arrange
    target_path = ORDERED_OTHER_PATHS[0]
    mock_get_device.return_value = DEVICE_ID_BASE
    mock_fs.is_dir.return_value = True  # For base_dir

    type_err = TypeError("FS method received bad type")

    def side_effect_exists(path):  # Changed lambda
        if path == target_path:  # target_path defined in test
            raise type_err  # Actually raise
        return path == BASE_DIR_PATH

    mock_fs.exists.side_effect = side_effect_exists

    # Act & Assert
    with pytest.raises(
        ConfigError,
        match=f"Error accessing or processing path '{target_path}': {type_err}",
    ):
        create_directories(mock_app_config, mock_fs)
