import os
import stat
from pathlib import Path
from unittest.mock import MagicMock
from typing import Callable

import pytest

from datamover.file_functions.safe_delete import safe_delete, DeleteValidationError


@pytest.fixture
def create_mock_stat_attrs():
    """
    Factory fixture to create a mock os.stat_result object.
    """

    def _make(st_mode, st_ino=123, st_size=1024):
        m = MagicMock(spec=os.stat_result)
        m.st_mode = st_mode
        m.st_ino = st_ino
        m.st_size = st_size
        return m

    return _make


# Note: 'mock_fs' and 'real_fs' fixtures are assumed to be provided by conftest.py

# --- Test Cases ---


def test_safe_delete_regular_file_real_fs(tmp_path: Path, real_fs):
    """Test safe_delete successfully deletes a regular file using real FS operations."""
    test_file = tmp_path / "regular_file.txt"
    test_file.write_text("content")
    assert test_file.exists()

    safe_delete(test_file, real_fs)

    assert not test_file.exists()


@pytest.mark.parametrize(
    "unlink_side_effect_exception",
    [
        None,  # Represents a successful unlink or file already gone (no error from fs.unlink)
        FileNotFoundError(
            "Mocked: FileNotFoundError from fs.unlink"
        ),  # fs.unlink itself raises FNF
    ],
    ids=[
        "unlink_success_or_already_gone",
        "unlink_raises_fnf_is_swallowed_by_safe_delete",
    ],
)
def test_safe_delete_mock_unlink_behaviors(
    tmp_path, mock_fs: MagicMock, create_mock_stat_attrs, unlink_side_effect_exception
):
    """
    Tests successful unlink scenarios with mock_fs.
    If fs.unlink (with missing_ok=True) raises FileNotFoundError,
    safe_delete (as per latest QA suggestion) should swallow this and succeed.
    Other exceptions from fs.unlink would be wrapped in DeleteValidationError (tested elsewhere).
    """
    p = tmp_path / "file.txt"
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=stat.S_IFREG | 0o644)

    if unlink_side_effect_exception is not None:
        mock_fs.unlink.side_effect = unlink_side_effect_exception

    # In both cases (fs.unlink succeeds/no-op, or fs.unlink raises FNF which safe_delete swallows),
    safe_delete(p, mock_fs)

    mock_fs.lstat.assert_called_once_with(p)
    mock_fs.unlink.assert_called_once_with(p, missing_ok=True)


# --- Parametrized Test for Lstat Phase Exception Scenarios (Mock FS) ---
@pytest.mark.parametrize(
    "exception_type_to_raise, exception_message_arg, expected_dve_message_template, test_id_suffix",
    [
        (
            FileNotFoundError,
            "Mocked: File not found by lstat",
            "Validation failed: file not found at '{path}'.",
            "FileNotFoundError_lstat",
        ),
        (
            PermissionError,
            "Mocked: Permission denied for lstat",
            "Validation failed: OS error during lstat of '{path}': {original_exception}",
            "PermissionError_lstat",
        ),
        (
            OSError,
            "Mocked: Some other OS error for lstat",
            "Validation failed: OS error during lstat of '{path}': {original_exception}",
            "OSError_other_lstat",
        ),
        (
            RuntimeError,
            "Mocked: Unexpected lstat failure",
            "Validation failed: Unexpected error during lstat of '{path}': {original_exception}",
            "RuntimeError_lstat",
        ),
    ],
    ids=[
        "lstat_file_not_found",
        "lstat_permission_denied",
        "lstat_other_os_error",
        "lstat_runtime_error_unexpected",
    ],
)
def test_safe_delete_lstat_phase_exception_scenarios_mock_fs(
    tmp_path: Path,
    mock_fs: MagicMock,
    exception_type_to_raise: type[Exception],
    exception_message_arg: str,
    expected_dve_message_template: str,
    test_id_suffix: str,
):
    """
    Tests that safe_delete correctly wraps various exceptions from fs.lstat
    into DeleteValidationError.
    """
    test_file = tmp_path / f"file_for_lstat_fail_{test_id_suffix}.txt"
    original_exception_instance = exception_type_to_raise(exception_message_arg)
    mock_fs.lstat.side_effect = original_exception_instance

    with pytest.raises(DeleteValidationError) as excinfo:
        safe_delete(test_file, mock_fs)

    if "{original_exception}" in expected_dve_message_template:
        expected_message = expected_dve_message_template.format(
            path=test_file, original_exception=original_exception_instance
        )
    else:
        expected_message = expected_dve_message_template.format(path=test_file)

    assert str(excinfo.value) == expected_message
    assert excinfo.value.__cause__ is original_exception_instance

    mock_fs.lstat.assert_called_once_with(test_file)
    mock_fs.unlink.assert_not_called()


# --- Parametrized Test for Non-Regular File Types (Mock FS) ---
@pytest.mark.parametrize(
    "file_type_name, mode_to_set",
    [
        ("directory", stat.S_IFDIR | 0o755),
        ("symlink", stat.S_IFLNK | 0o777),
    ],
    ids=["directory_mock", "symlink_mock"],
)
def test_safe_delete_non_regular_file_type_mock_fs(
    tmp_path: Path,
    mock_fs: MagicMock,
    create_mock_stat_attrs,
    file_type_name: str,
    mode_to_set: int,
):
    """Test safe_delete raises DeleteValidationError for various non-regular file types using mock_fs."""
    test_path = tmp_path / f"some_{file_type_name}"
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=mode_to_set)

    with pytest.raises(DeleteValidationError) as excinfo:
        safe_delete(test_path, mock_fs)

    expected_msg_part = f"Validation failed: path '{test_path}' is not a regular file"
    assert expected_msg_part in str(excinfo.value)
    assert f"detected: {stat.filemode(mode_to_set)}" in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    mock_fs.lstat.assert_called_once_with(test_path)
    mock_fs.unlink.assert_not_called()


# --- Helper functions for setting up real non-regular file types ---
def _setup_real_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    assert path.is_dir()


def _setup_real_symlink(path: Path, tmp_path: Path):
    target_file = tmp_path / f"target_for_{path.name}.txt"
    if not target_file.exists():
        target_file.write_text("symlink target content")
    path.symlink_to(target_file)
    assert path.is_symlink()
    return target_file


# --- Parametrized Test for Non-Regular File Types (Real FS) ---
@pytest.mark.parametrize(
    "file_type_name, setup_action",
    [
        ("directory", _setup_real_directory),
        ("symlink", _setup_real_symlink),
    ],
    ids=["real_directory", "real_symlink"],
)
def test_safe_delete_non_regular_file_type_real_fs(
    tmp_path: Path, real_fs, file_type_name: str, setup_action: Callable
):
    """Test safe_delete on real non-regular file types raises DeleteValidationError."""
    test_path = tmp_path / f"actual_{file_type_name}"
    target_file_for_symlink = None

    if file_type_name == "symlink":
        target_file_for_symlink = setup_action(test_path, tmp_path)
    else:
        setup_action(test_path)

    with pytest.raises(DeleteValidationError) as excinfo:
        safe_delete(test_path, real_fs)

    assert f"Validation failed: path '{test_path}' is not a regular file" in str(
        excinfo.value
    )
    assert excinfo.value.__cause__ is None
    assert test_path.exists()

    if file_type_name == "symlink" and target_file_for_symlink:
        assert target_file_for_symlink.exists()


# --- Parametrized Test for Unlink Phase Failure Scenarios (Mock FS) ---
# (Excluding FileNotFoundError from fs.unlink, as that's now swallowed by safe_delete)
@pytest.mark.parametrize(
    "exception_to_raise, description",
    [
        (
            IsADirectoryError("Mocked: Is a directory during unlink"),
            "IsADirectoryError_unlink",
        ),
        (
            PermissionError("Mocked: Permission denied for unlink"),
            "PermissionError_unlink",
        ),
        (OSError("Mocked: Some other OS error during unlink"), "OSError_other_unlink"),
        (RuntimeError("Mocked: Unexpected unlink failure"), "RuntimeError_unlink"),
    ],
    ids=[
        "race_becomes_dir_during_unlink",
        "permission_denied_during_unlink",
        "other_os_error_during_unlink",
        "runtime_error_during_unlink",
    ],
)
def test_safe_delete_unlink_phase_failure_scenarios_mock_fs(
    tmp_path: Path,
    mock_fs: MagicMock,
    create_mock_stat_attrs,
    exception_to_raise: Exception,
    description: str,
):
    """
    Tests that safe_delete wraps various exceptions (excluding FileNotFoundError)
    from the fs.unlink call into DeleteValidationError.
    """
    test_file = tmp_path / f"file_for_unlink_fail_{description}.txt"
    mock_fs.lstat.return_value = create_mock_stat_attrs(st_mode=stat.S_IFREG | 0o644)
    mock_fs.unlink.side_effect = exception_to_raise

    with pytest.raises(DeleteValidationError) as excinfo:
        safe_delete(test_file, mock_fs)

    assert f"Deletion failed: could not unlink '{test_file}'" in str(excinfo.value)
    assert excinfo.value.__cause__ is exception_to_raise

    mock_fs.lstat.assert_called_once_with(test_file)
    mock_fs.unlink.assert_called_once_with(test_file, missing_ok=True)
