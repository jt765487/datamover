import logging
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

from datamover.file_functions.determin_destination import determine_destination


@pytest.fixture
def initial_path(tmp_path: Path) -> Path:
    return tmp_path / "dest" / "dir" / "file.txt"


@pytest.fixture
def source_name() -> str:
    return "file.txt"


@pytest.fixture
def unique_path(initial_path: Path) -> Path:  # Or also based on tmp_path directly
    return initial_path.with_name(f"{initial_path.stem}_1{initial_path.suffix}")


# --- Patch Definition ---
# Patch find_available_target_path where it's IMPORTED by determine_destination
FIND_AVAILABLE_PATCH = (
    "datamover.file_functions.determin_destination.find_available_target_path"
)


# --- Tests Updated for Patching ---


@patch(FIND_AVAILABLE_PATCH)  # Patch the internal helper
def test_determine_destination_no_conflict(
    mock_find_available: Mock,  # Mock passed by patch
    initial_path: Path,
    source_name: str,
    mock_fs: Mock,
):
    """Test returns initial path if fs.exists returns False."""
    mock_fs.exists.return_value = False

    # Call function normally
    result = determine_destination(
        initial_path,
        source_name,
        mock_fs,
    )

    assert result == initial_path
    mock_fs.exists.assert_called_once_with(initial_path)
    mock_find_available.assert_not_called()  # Patched function not called


@patch(FIND_AVAILABLE_PATCH)  # Patch the internal helper
def test_determine_destination_conflict_resolved(
    mock_find_available: Mock,  # Mock passed by patch
    initial_path: Path,
    source_name: str,
    unique_path: Path,
    mock_fs: Mock,
    caplog,
):
    """Test returns unique path if fs.exists is True and finder succeeds."""
    mock_fs.exists.return_value = True
    # Configure the *patched* function's return value
    mock_find_available.return_value = unique_path
    caplog.set_level(logging.INFO)

    # Call function normally
    result = determine_destination(
        initial_path,
        source_name,
        mock_fs,
    )

    assert result == unique_path
    mock_fs.exists.assert_called_once_with(initial_path)
    # Verify the *patched* function was called correctly
    mock_find_available.assert_called_once_with(base_path=initial_path, fs=mock_fs)
    assert f"Proposed path '{initial_path}' already exists" in caplog.text
    assert f"Using unique path: '{unique_path}'" in caplog.text


@patch(FIND_AVAILABLE_PATCH)  # Patch the internal helper
def test_determine_destination_conflict_resolution_fails(
    mock_find_available: Mock,  # Mock passed by patch
    initial_path: Path,
    source_name: str,
    mock_fs: Mock,
    caplog,
):
    """Test returns None if fs.exists is True and finder fails."""
    mock_fs.exists.return_value = True
    # Configure the *patched* function to fail
    mock_find_available.return_value = None
    caplog.set_level(logging.WARNING)

    # Call function normally
    result = determine_destination(
        initial_path,
        source_name,
        mock_fs,
    )

    assert result is None
    mock_fs.exists.assert_called_once_with(initial_path)  # This should pass now
    # Verify the *patched* function was called
    mock_find_available.assert_called_once_with(base_path=initial_path, fs=mock_fs)
    assert f"Proposed path '{initial_path}' already exists" in caplog.text
    assert "CONFLICT RESOLUTION FAILED" in caplog.text


@patch(FIND_AVAILABLE_PATCH)  # Patch the internal helper
def test_determine_destination_fs_exists_raises_oserror(
    mock_find_available: Mock,  # Mock passed by patch
    initial_path: Path,
    source_name: str,
    mock_fs: Mock,
    caplog,
):
    """Test returns None if fs.exists raises OSError."""
    error = OSError("Disk read error")
    mock_fs.exists.side_effect = error
    caplog.set_level(logging.ERROR)

    # Call function normally
    result = determine_destination(
        initial_path,
        source_name,
        mock_fs,
    )

    assert result is None
    mock_fs.exists.assert_called_once_with(initial_path)
    mock_find_available.assert_not_called()  # Patched function not called
    assert "OSError checking/determining destination path" in caplog.text
    assert str(error) in caplog.text


@patch(FIND_AVAILABLE_PATCH)  # Patch the internal helper
def test_determine_destination_unexpected_error(
    mock_find_available: Mock,  # Mock passed by patch
    initial_path: Path,
    source_name: str,
    mock_fs: Mock,
    caplog,
):
    """Test returns None on unexpected error during processing."""
    error = ValueError("Unexpected issue")
    mock_fs.exists.side_effect = error
    caplog.set_level(logging.ERROR)

    # Call function normally
    result = determine_destination(
        initial_path,
        source_name,
        mock_fs,
    )

    assert result is None
    mock_fs.exists.assert_called_once_with(initial_path)
    mock_find_available.assert_not_called()  # Patched function not called
    assert "Unexpected error determining destination path" in caplog.text
    assert caplog.records[0].exc_info is not None
    assert isinstance(caplog.records[0].exc_info[1], ValueError)
