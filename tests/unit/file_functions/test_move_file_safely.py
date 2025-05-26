import logging
from pathlib import Path
from typing import Optional
from unittest.mock import (
    patch,
    Mock,
)

import pytest

from datamover.file_functions.move_file_safely import (
    move_file_safely_impl,
)


# --- Fixtures ---

# The local mock_fs fixture is REMOVED. It will come from conftest.py.


@pytest.fixture
def source_path() -> Path:
    return Path("/origin/source_file.txt")


@pytest.fixture
def destination_dir() -> Path:
    return Path("/final/dest_dir")


@pytest.fixture
def expected_source_dir(source_path: Path) -> Path:
    return source_path.parent


@pytest.fixture
def resolved_source_path(source_path: Path) -> Path:
    return Path(
        "/resolved/origin/source_file.txt"
    )  # Made distinct for clarity if needed


@pytest.fixture
def final_destination_path(destination_dir: Path, resolved_source_path: Path) -> Path:
    return destination_dir / resolved_source_path.name


def create_mock_stat_result_tuple(is_reg: bool = True) -> Optional[tuple[int, int]]:
    if not is_reg:
        return None
    # These values (device_id, size) are illustrative for the tuple
    return 12345, 1024


# --- Patch Definitions (relative to move_file_safely_impl's location) ---
VALIDATE_PATCH = "datamover.file_functions.move_file_safely.validate_file"
SAFE_STAT_PATCH = "datamover.file_functions.move_file_safely.safe_stat"
DETERMINE_PATCH = "datamover.file_functions.move_file_safely.determine_destination"
EXECUTE_PATCH = "datamover.file_functions.move_file_safely.execute_move_file"

# --- Test Cases ---

# Test cases remain largely the same, just relying on the global mock_fs


@patch(EXECUTE_PATCH)
@patch(DETERMINE_PATCH)
@patch(SAFE_STAT_PATCH)
@patch(VALIDATE_PATCH)
def test_success_full_validation(
    mock_validate_file: Mock,
    mock_safe_stat: Mock,
    mock_determine_destination_helper: Mock,
    mock_execute_move: Mock,
    mock_fs: Mock,  # Injected from conftest.py
    source_path: Path,
    destination_dir: Path,
    expected_source_dir: Path,
    resolved_source_path: Path,
    final_destination_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Tests the success path when full validation is requested."""
    # Arrange
    mock_validate_file.return_value = resolved_source_path
    mock_determine_destination_helper.return_value = final_destination_path
    mock_execute_move.return_value = True
    caplog.set_level(logging.DEBUG)

    # Act
    result = move_file_safely_impl(
        source_path_raw=source_path,
        destination_dir=destination_dir,
        fs=mock_fs,
        expected_source_dir=expected_source_dir,
    )

    # Assert
    assert result == final_destination_path
    mock_validate_file.assert_called_once_with(
        source_path_input=source_path,
        expected_source_dir=expected_source_dir,
        fs=mock_fs,
    )

    mock_safe_stat.assert_not_called()  # This is the *patched* safe_stat, not fs.stat
    mock_fs.resolve.assert_not_called()  # This is fs.resolve from the FS interface
    mock_determine_destination_helper.assert_called_once_with(
        initial_dest_path=(destination_dir / resolved_source_path.name),
        source_name_for_log=resolved_source_path.name,
        fs=mock_fs,
    )
    mock_execute_move.assert_called_once_with(
        resolved_source_path=resolved_source_path,
        final_dest_path=final_destination_path,
        fs=mock_fs,
    )
    assert (
        f"Successfully moved '{resolved_source_path}' to '{final_destination_path}'"
        in caplog.text
    )
    for record in caplog.records:
        assert record.levelno < logging.ERROR


@patch(EXECUTE_PATCH)
@patch(DETERMINE_PATCH)
@patch(SAFE_STAT_PATCH)  # This patches '...move_file_safely.safe_stat'
@patch(VALIDATE_PATCH)
def test_success_basic_validation(
    mock_validate_file: Mock,
    mock_safe_stat_helper: Mock,  # This is the mock for '...move_file_safely.safe_stat'
    mock_determine_destination_helper: Mock,
    mock_execute_move: Mock,
    mock_fs: Mock,  # Injected from conftest.py
    source_path: Path,
    destination_dir: Path,
    resolved_source_path: Path,
    final_destination_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Tests the success path when basic validation is used (expected_source_dir is None)."""
    # Arrange
    # In basic validation, _basic_resolve_source is called.
    # _basic_resolve_source calls the (patched) 'safe_stat' and then 'fs.resolve'.
    mock_safe_stat_helper.return_value = create_mock_stat_result_tuple(is_reg=True)
    mock_fs.resolve.return_value = resolved_source_path  # Configure the fs.resolve mock
    mock_determine_destination_helper.return_value = final_destination_path
    mock_execute_move.return_value = True
    caplog.set_level(logging.DEBUG)

    # Act
    result = move_file_safely_impl(
        source_path_raw=source_path,
        destination_dir=destination_dir,
        fs=mock_fs,
        expected_source_dir=None,  # This triggers basic validation
    )

    # Assert
    assert result == final_destination_path
    mock_validate_file.assert_not_called()
    mock_safe_stat_helper.assert_called_once_with(path=source_path, fs=mock_fs)
    mock_fs.resolve.assert_called_once_with(source_path, strict=True)
    mock_determine_destination_helper.assert_called_once_with(
        initial_dest_path=(destination_dir / resolved_source_path.name),
        source_name_for_log=resolved_source_path.name,
        fs=mock_fs,
    )
    mock_execute_move.assert_called_once_with(
        resolved_source_path=resolved_source_path,
        final_dest_path=final_destination_path,
        fs=mock_fs,
    )
    assert (
        f"Successfully moved '{resolved_source_path}' to '{final_destination_path}'"
        in caplog.text
    )
    for record in caplog.records:
        assert record.levelno < logging.ERROR


@patch(EXECUTE_PATCH)
@patch(DETERMINE_PATCH)
@patch(SAFE_STAT_PATCH)  # Patches '...move_file_safely.safe_stat'
@patch(VALIDATE_PATCH)
def test_fail_full_validation(
    mock_validate_file: Mock,
    mock_safe_stat: Mock,  # This is the mock for '...move_file_safely.safe_stat'
    mock_determine_destination_helper: Mock,
    mock_execute_move: Mock,
    mock_fs: Mock,  # Injected from conftest.py
    source_path: Path,
    destination_dir: Path,
    expected_source_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    # Arrange
    mock_validate_file.return_value = None  # Simulate validation failure
    caplog.set_level(logging.ERROR)

    # Act
    result = move_file_safely_impl(
        source_path_raw=source_path,
        destination_dir=destination_dir,
        fs=mock_fs,
        expected_source_dir=expected_source_dir,
    )

    # Assert
    assert result is None
    mock_validate_file.assert_called_once_with(
        source_path_input=source_path,
        expected_source_dir=expected_source_dir,
        fs=mock_fs,
    )
    mock_safe_stat.assert_not_called()
    mock_fs.resolve.assert_not_called()
    mock_determine_destination_helper.assert_not_called()
    mock_execute_move.assert_not_called()

    expected_exception_message = (
        f"Full validation failed for '{source_path}'. "
        "See previous logs from validate_file for details."
    )
    assert (
        f"Move aborted for '{source_path}': {expected_exception_message}" in caplog.text
    )


@patch(EXECUTE_PATCH)
@patch(DETERMINE_PATCH)
@patch(SAFE_STAT_PATCH)  # Patches '...move_file_safely.safe_stat'
@patch(VALIDATE_PATCH)
def test_fail_basic_safe_stat(
    mock_validate_file: Mock,
    mock_safe_stat_helper: Mock,  # This is the mock for '...move_file_safely.safe_stat'
    mock_determine_destination_helper: Mock,
    mock_execute_move: Mock,
    mock_fs: Mock,  # Injected from conftest.py
    source_path: Path,
    destination_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    # Arrange
    mock_safe_stat_helper.return_value = None  # Simulate safe_stat failure
    caplog.set_level(logging.ERROR)

    # Act
    result = move_file_safely_impl(
        source_path_raw=source_path,
        destination_dir=destination_dir,
        fs=mock_fs,
        expected_source_dir=None,  # Basic validation path
    )

    # Assert
    assert result is None
    mock_validate_file.assert_not_called()
    mock_safe_stat_helper.assert_called_once_with(path=source_path, fs=mock_fs)
    mock_fs.resolve.assert_not_called()  # fs.resolve is not reached if safe_stat fails
    mock_determine_destination_helper.assert_not_called()
    mock_execute_move.assert_not_called()

    expected_exception_message = f"Basic source check (safe_stat) failed for '{source_path}'. See previous logs from safe_stat."
    assert (
        f"Move aborted for '{source_path}': {expected_exception_message}" in caplog.text
    )


@patch(EXECUTE_PATCH)
@patch(DETERMINE_PATCH)
@patch(SAFE_STAT_PATCH)  # Patches '...move_file_safely.safe_stat'
@patch(VALIDATE_PATCH)
def test_fail_basic_fs_resolve_not_found(
    mock_validate_file: Mock,
    mock_safe_stat_helper: Mock,  # This is the mock for '...move_file_safely.safe_stat'
    mock_determine_destination_helper: Mock,
    mock_execute_move: Mock,
    mock_fs: Mock,  # Injected from conftest.py
    source_path: Path,
    destination_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    # Arrange
    mock_safe_stat_helper.return_value = create_mock_stat_result_tuple(is_reg=True)
    original_error = FileNotFoundError(f"Resolve test error for {source_path}")
    mock_fs.resolve.side_effect = original_error  # Configure fs.resolve to fail
    caplog.set_level(logging.ERROR)

    # Act
    result = move_file_safely_impl(
        source_path_raw=source_path,
        destination_dir=destination_dir,
        fs=mock_fs,
        expected_source_dir=None,  # Basic validation path
    )

    # Assert
    assert result is None
    mock_validate_file.assert_not_called()
    mock_safe_stat_helper.assert_called_once_with(path=source_path, fs=mock_fs)
    mock_fs.resolve.assert_called_once_with(source_path, strict=True)
    mock_determine_destination_helper.assert_not_called()
    mock_execute_move.assert_not_called()

    expected_exception_message = (
        f"Source '{source_path}' not found during path resolution: {original_error}"
    )
    assert (
        f"Move aborted for '{source_path}': {expected_exception_message}" in caplog.text
    )


@pytest.mark.parametrize(
    "exception_type_to_raise, error_message_in_log_fragment",
    [
        (
            TypeError("Invalid type for resolve test"),
            "Invalid source path type for resolution",
        ),
        (OSError("OS error during resolve test"), "OS error during path resolution"),
        (
            Exception("Unexpected resolve error test"),
            "Unexpected error during path resolution",
        ),
    ],
)
@patch(EXECUTE_PATCH)
@patch(DETERMINE_PATCH)
@patch(SAFE_STAT_PATCH)  # Patches '...move_file_safely.safe_stat'
@patch(VALIDATE_PATCH)
def test_fail_basic_fs_resolve_other_exceptions(
    mock_validate_file: Mock,
    mock_safe_stat_helper: Mock,  # This is the mock for '...move_file_safely.safe_stat'
    mock_determine_destination_helper: Mock,
    mock_execute_move: Mock,
    exception_type_to_raise: Exception,
    error_message_in_log_fragment: str,
    mock_fs: Mock,  # Injected from conftest.py
    source_path: Path,
    destination_dir: Path,
    caplog: pytest.LogCaptureFixture,
):
    # Arrange
    mock_safe_stat_helper.return_value = create_mock_stat_result_tuple(is_reg=True)
    mock_fs.resolve.side_effect = exception_type_to_raise
    caplog.set_level(logging.ERROR)

    # Act
    result = move_file_safely_impl(
        source_path_raw=source_path,
        destination_dir=destination_dir,
        fs=mock_fs,
        expected_source_dir=None,  # Basic validation path
    )

    # Assert
    assert result is None
    mock_validate_file.assert_not_called()
    mock_safe_stat_helper.assert_called_once_with(path=source_path, fs=mock_fs)
    mock_fs.resolve.assert_called_once_with(source_path, strict=True)
    mock_determine_destination_helper.assert_not_called()
    mock_execute_move.assert_not_called()

    expected_exception_message_part = (
        f"{error_message_in_log_fragment} of '{source_path}': {exception_type_to_raise}"
    )
    assert (
        f"Move aborted for '{source_path}': {expected_exception_message_part}"
        in caplog.text
    )


@patch(EXECUTE_PATCH)
@patch(DETERMINE_PATCH)
@patch(SAFE_STAT_PATCH)  # Patches '...move_file_safely.safe_stat'
@patch(VALIDATE_PATCH)
def test_fail_determine_destination(
    mock_validate_file: Mock,
    mock_safe_stat: Mock,  # This is the mock for '...move_file_safely.safe_stat'
    mock_determine_destination_helper: Mock,
    mock_execute_move: Mock,
    mock_fs: Mock,  # Injected from conftest.py
    source_path: Path,
    destination_dir: Path,
    expected_source_dir: Path,
    resolved_source_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    # Arrange
    mock_validate_file.return_value = resolved_source_path  # Full validation path
    mock_determine_destination_helper.return_value = None  # Simulate failure
    caplog.set_level(logging.ERROR)

    # Act
    result = move_file_safely_impl(
        source_path_raw=source_path,
        destination_dir=destination_dir,
        fs=mock_fs,
        expected_source_dir=expected_source_dir,
    )

    # Assert
    assert result is None
    mock_validate_file.assert_called_once()
    mock_safe_stat.assert_not_called()  # Not called in full validation path directly by SUT
    mock_determine_destination_helper.assert_called_once_with(
        initial_dest_path=(destination_dir / resolved_source_path.name),
        source_name_for_log=resolved_source_path.name,
        fs=mock_fs,
    )
    mock_execute_move.assert_not_called()

    expected_exception_message = (
        f"Could not determine a valid final destination for '{resolved_source_path.name}' "
        f"in '{destination_dir}'. See previous logs from determine_destination."
    )
    assert (
        f"Move aborted for '{source_path}': {expected_exception_message}" in caplog.text
    )


@patch(EXECUTE_PATCH)
@patch(DETERMINE_PATCH)
@patch(SAFE_STAT_PATCH)  # Patches '...move_file_safely.safe_stat'
@patch(VALIDATE_PATCH)
def test_fail_execute_move(
    mock_validate_file: Mock,
    mock_safe_stat: Mock,  # This is the mock for '...move_file_safely.safe_stat'
    mock_determine_destination_helper: Mock,
    mock_execute_move: Mock,
    mock_fs: Mock,  # Injected from conftest.py
    source_path: Path,
    destination_dir: Path,
    expected_source_dir: Path,
    resolved_source_path: Path,
    final_destination_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    # Arrange
    mock_validate_file.return_value = resolved_source_path  # Full validation path
    mock_determine_destination_helper.return_value = final_destination_path
    mock_execute_move.return_value = False  # Simulate move failure
    caplog.set_level(logging.ERROR)

    # Act
    result = move_file_safely_impl(
        source_path_raw=source_path,
        destination_dir=destination_dir,
        fs=mock_fs,
        expected_source_dir=expected_source_dir,
    )

    # Assert
    assert result is None
    mock_validate_file.assert_called_once()
    mock_safe_stat.assert_not_called()  # Not called in full validation path directly by SUT
    mock_determine_destination_helper.assert_called_once()
    mock_execute_move.assert_called_once_with(
        resolved_source_path=resolved_source_path,
        final_dest_path=final_destination_path,
        fs=mock_fs,
    )

    expected_exception_message = (
        f"File move execution failed for '{resolved_source_path}' to '{final_destination_path}'. "
        "See previous logs from execute_move_file for details."
    )
    assert (
        f"Move aborted for '{source_path}': {expected_exception_message}" in caplog.text
    )
