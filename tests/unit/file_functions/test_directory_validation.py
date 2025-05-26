import logging
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from datamover.file_functions.directory_validation import (
    resolve_and_validate_directory,
)


@pytest.fixture
def test_raw_path() -> Path:
    """Sample raw Path for testing resolution."""
    return Path("./data/input")


@pytest.fixture
def test_resolved_path() -> Path:
    """Expected resolved Path after fs.resolve."""
    return Path("/abs/path/to/data/input")


@pytest.fixture
def dir_label() -> str:
    """Sample directory label for error messages."""
    return "source data"


def test_resolve_validate_success(
    mock_fs: Mock, test_raw_path: Path, test_resolved_path: Path, dir_label: str
):
    """Returns resolved path when it exists and is a directory."""
    mock_fs.resolve.return_value = test_resolved_path
    mock_fs.is_dir.return_value = True

    result = resolve_and_validate_directory(test_raw_path, mock_fs, dir_label)

    assert result == test_resolved_path
    mock_fs.resolve.assert_called_once_with(test_raw_path, strict=True)
    mock_fs.is_dir.assert_called_once_with(test_resolved_path)


def test_resolve_validate_not_found_error(
    mock_fs: Mock, test_raw_path: Path, dir_label: str, caplog: pytest.LogCaptureFixture
):
    """Propagates FileNotFoundError and logs an error if path not found."""
    original = FileNotFoundError(f"Mocked: Cannot resolve {test_raw_path}")
    mock_fs.resolve.side_effect = original
    caplog.set_level(logging.ERROR)

    with pytest.raises(FileNotFoundError) as exc:
        resolve_and_validate_directory(test_raw_path, mock_fs, dir_label)

    assert exc.value is original
    mock_fs.resolve.assert_called_once_with(test_raw_path, strict=True)
    mock_fs.is_dir.assert_not_called()
    assert (
        f"Validation Failed: {dir_label} directory '{test_raw_path}' not found."
        in caplog.text
    )


def test_resolve_validate_not_a_directory_error(
    mock_fs: Mock,
    test_raw_path: Path,
    test_resolved_path: Path,
    dir_label: str,
    caplog: pytest.LogCaptureFixture,
):
    """Raises NotADirectoryError and logs when resolved path isn’t a directory."""
    mock_fs.resolve.return_value = test_resolved_path
    mock_fs.is_dir.return_value = False
    caplog.set_level(logging.ERROR)

    msg = f"{dir_label.capitalize()} path '{test_resolved_path}' exists but is not a directory (checked via FS)."
    with pytest.raises(NotADirectoryError, match=re.escape(msg)):
        resolve_and_validate_directory(test_raw_path, mock_fs, dir_label)

    mock_fs.resolve.assert_called_once_with(test_raw_path, strict=True)
    mock_fs.is_dir.assert_called_once_with(test_resolved_path)
    assert f"Validation Failed: {msg}" in caplog.text


def test_resolve_validate_type_error_propagates_from_resolve(
    mock_fs: Mock, test_raw_path: Path, dir_label: str, caplog: pytest.LogCaptureFixture
):
    """Propagates TypeError from resolve and logs an error."""
    original = TypeError("Mocked: FS resolve received incompatible type")
    mock_fs.resolve.side_effect = original
    caplog.set_level(logging.ERROR)

    with pytest.raises(TypeError, match=re.escape(str(original))) as exc:
        resolve_and_validate_directory(test_raw_path, mock_fs, dir_label)

    assert exc.value is original
    mock_fs.resolve.assert_called_once_with(test_raw_path, strict=True)
    mock_fs.is_dir.assert_not_called()
    assert (
        f"Validation Failed: TypeError during FS operation for {dir_label} directory '{test_raw_path}'. {original}"
        in caplog.text
    )


# Parameterized scenarios for exceptions wrapped in ValueError

WRAPPED_EXCEPTION_SCENARIOS = [
    pytest.param(
        "resolve",
        OSError("Mocked: Permission denied during resolve"),
        id="fs_resolve_raises_os_error",
    ),
    pytest.param(
        "is_dir",
        OSError("Mocked: Permission denied during is_dir check"),
        id="fs_is_dir_raises_os_error",
    ),
    pytest.param(
        "resolve",
        RuntimeError("Mocked: Unexpected error in resolve"),
        id="fs_resolve_raises_unexpected_exception",
    ),
    pytest.param(
        "is_dir",
        RuntimeError("Mocked: Unexpected error in is_dir"),
        id="fs_is_dir_raises_unexpected_exception",
    ),
]


@pytest.mark.parametrize(
    "failing_method_name,error_to_raise", WRAPPED_EXCEPTION_SCENARIOS
)
def test_resolve_validate_wrapped_errors(
    mock_fs: Mock,
    test_raw_path: Path,
    test_resolved_path: Path,
    dir_label: str,
    caplog: pytest.LogCaptureFixture,
    failing_method_name: str,
    error_to_raise: Exception,
):
    """Wraps OSError/RuntimeError from FS methods in ValueError and logs the original."""
    caplog.set_level(logging.ERROR)

    if failing_method_name == "resolve":
        mock_fs.resolve.side_effect = error_to_raise
    else:
        mock_fs.resolve.return_value = test_resolved_path
        mock_fs.is_dir.side_effect = error_to_raise

    wrapper = (
        "OS error validating"
        if isinstance(error_to_raise, OSError)
        else "Unexpected error validating"
    )
    expected_wrapper = f"{wrapper} {dir_label} directory '{test_raw_path}' using FS"

    with pytest.raises(ValueError, match=re.escape(expected_wrapper)) as exc:
        resolve_and_validate_directory(test_raw_path, mock_fs, dir_label)

    assert exc.value.__cause__ is error_to_raise
    mock_fs.resolve.assert_called_once_with(test_raw_path, strict=True)
    if failing_method_name == "is_dir":
        mock_fs.is_dir.assert_called_once_with(test_resolved_path)
    else:
        mock_fs.is_dir.assert_not_called()

    log_type = "OS error" if isinstance(error_to_raise, OSError) else "Unexpected error"
    expected_log = f"Validation Failed: {log_type} for {dir_label} directory '{test_raw_path}': {error_to_raise}"
    assert any(
        record.levelname == "ERROR" and expected_log in record.message
        for record in caplog.records
    )
