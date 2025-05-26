import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from datamover.file_functions.execute_move_file import execute_move_file
from tests.test_utils.logging_helpers import find_log_record


@pytest.fixture
def paths(tmp_path: Path) -> tuple[Path, Path]:
    """
    Provides dynamic source and destination Paths under tmp_path.
    """
    src = tmp_path / "src" / "file.txt"
    dst = tmp_path / "dst" / "file.txt"
    return src, dst


def test_execute_move_success(
    paths: tuple[Path, Path], mock_fs: Mock, caplog: pytest.LogCaptureFixture
):
    source, dest = paths
    caplog.set_level(logging.DEBUG)

    result = execute_move_file(source, dest, fs=mock_fs)

    assert result is True
    mock_fs.move.assert_called_once_with(source, dest)

    # Check for a DEBUG log indicating execution, containing source and destination
    debug_log = find_log_record(
        caplog, logging.DEBUG, ["Executing move", str(source), str(dest)]
    )
    assert debug_log is not None, (
        "DEBUG log for move execution not found or missing key info."
    )


def test_execute_move_file_not_found(
    paths: tuple[Path, Path], mock_fs: Mock, caplog: pytest.LogCaptureFixture
):
    source, dest = paths
    exception_instance = FileNotFoundError("Mock: Source vanished via FS")
    mock_fs.move.side_effect = exception_instance
    caplog.set_level(logging.WARNING)

    result = execute_move_file(source, dest, fs=mock_fs)

    assert result is True
    mock_fs.move.assert_called_once_with(source, dest)

    # Check for a WARNING log about the missing file, containing source and destination
    # and the key phrase "does not exist" and "Considered successful"
    warning_log = find_log_record(
        caplog,
        logging.WARNING,
        [
            "Source file",
            str(source),
            "does not exist",
            str(dest),
            "Considered successful",
        ],
    )
    assert warning_log is not None, (
        "WARNING log for FileNotFoundError not found or missing key info."
    )


@pytest.mark.parametrize(
    "error_type, error_keyword, is_generic_exception_handler",
    [
        (PermissionError("Mock: Permission denied"), "PermissionError", False),
        (OSError("Mock: Disk full"), "OSError", False),
        (ValueError("Mock: Unexpected issue"), "Unexpected error", True),
    ],
)
def test_execute_move_failures(
    paths: tuple[Path, Path],
    mock_fs: Mock,
    caplog: pytest.LogCaptureFixture,
    error_type: Exception,
    error_keyword: str,
    is_generic_exception_handler: bool,
):
    source, dest = paths
    caplog.set_level(logging.ERROR)
    mock_fs.move.side_effect = error_type

    result = execute_move_file(source, dest, fs=mock_fs)

    assert result is False
    mock_fs.move.assert_called_once_with(source, dest)

    # Find the relevant ERROR log record
    # It should contain the error keyword, source, and destination path
    required_in_message = [error_keyword, str(source), str(dest)]
    if not is_generic_exception_handler:
        # For specific handlers (logger.error("... %s", e)), str(e) is in the message
        required_in_message.append(str(error_type))

    error_log = find_log_record(caplog, logging.ERROR, required_in_message)
    assert error_log is not None, (
        f"ERROR log for {error_keyword} not found or missing key info."
    )

    if is_generic_exception_handler:
        # logger.exception was used
        assert error_log.exc_info is not None, (
            "exc_info should be set by logger.exception"
        )
        assert isinstance(error_log.exc_info[1], type(error_type)), (
            "Incorrect exception type in exc_info"
        )
        # For logger.exception, str(error_type) is part of exc_text, not directly in message
        assert str(error_type) not in error_log.message, (
            "str(error) should not be in message for logger.exception"
        )
        assert str(error_type) in error_log.exc_text, (
            "str(error) should be in exc_text for logger.exception"
        )

    else:
        # logger.error was used without exc_info=True (by default)
        assert error_log.exc_info is None, (
            "exc_info should not be set by default for logger.error"
        )
