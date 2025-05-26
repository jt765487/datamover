import logging
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from datamover.file_functions.find_available_target_path import (
    find_available_target_path,
)

from tests.test_utils.logging_helpers import find_log_record

# --- Test Cases ---


@pytest.mark.parametrize(
    "base_path_str, expected_candidate_str",
    [
        ("/target/file.txt", "/target/file-1.txt"),
        ("/target/filenoext", "/target/filenoext-1"),
        ("/target/archive.tar.gz", "/target/archive.tar-1.gz"),
        ("/target/.config", "/target/.config-1"),
        ("/target/.config.ini", "/target/.config-1.ini"),
    ],
    ids=[
        "with_suffix",
        "no_suffix",
        "multi_dot_suffix",
        "hidden_no_suffix",
        "hidden_with_suffix",
    ],
)
def test_first_attempt_succeeds_for_various_paths(
    mock_fs_configured: Mock,  # Use the descriptive name from conftest
    base_path_str: str,
    expected_candidate_str: str,
):
    """
    Test finds '<stem-parts>-1.<suffix-part>' if the first candidate path doesn't exist.
    """
    base_path = Path(base_path_str)
    expected_path = Path(expected_candidate_str)
    # mock_fs_configured.exists defaults to return_value=False from the conftest fixture

    result = find_available_target_path(base_path=base_path, fs=mock_fs_configured)

    assert result == expected_path
    mock_fs_configured.exists.assert_called_once_with(expected_path)


def test_multiple_attempts_succeed(mock_fs_configured: Mock):
    """
    Test finds the next available numbered path when earlier candidates exist.
    E.g., finds 'stem-3.suffix' if 'stem-1.suffix' and 'stem-2.suffix' exist.
    """
    base_path = Path("/target/file.txt")
    # Concise set comprehension for existing paths
    existing_paths = {Path(f"/target/file-{i}.txt") for i in (1, 2)}

    # Override the default .exists behavior for this specific test
    mock_fs_configured.exists.side_effect = lambda p: p in existing_paths

    result = find_available_target_path(base_path=base_path, fs=mock_fs_configured)

    expected_path = Path("/target/file-3.txt")
    assert result == expected_path
    assert mock_fs_configured.exists.call_count == 3
    mock_fs_configured.exists.assert_has_calls(
        [
            call(Path("/target/file-1.txt")),
            call(Path("/target/file-2.txt")),
            call(Path("/target/file-3.txt")),
        ],
        any_order=False,  # Order is important for this logic
    )


def test_limit_reached_returns_none_and_logs(
    mock_fs_configured: Mock, caplog: pytest.LogCaptureFixture
):
    """
    Test returns None and logs an error if no candidate path is free within the attempt limit.
    """
    base_path = Path("/target/file.txt")
    limit = 5
    mock_fs_configured.exists.return_value = (
        True  # All attempts will find existing files
    )
    caplog.set_level(logging.ERROR)

    result = find_available_target_path(
        base_path=base_path, limit=limit, fs=mock_fs_configured
    )

    assert result is None
    assert mock_fs_configured.exists.call_count == limit
    expected_calls = [call(Path(f"/target/file-{i}.txt")) for i in range(1, limit + 1)]
    mock_fs_configured.exists.assert_has_calls(expected_calls, any_order=False)

    error_log = find_log_record(
        caplog,
        logging.ERROR,
        ["Could not find available path", base_path.name, str(limit)],
    )
    assert error_log is not None, (
        "Error log for limit reached not found or missing key info."
    )


@pytest.mark.parametrize(
    "exception_to_raise, expected_log_keyword, is_generic_exception_handler",
    [
        (OSError("Disk permission error"), "OSError checking existence", False),
        (
            ValueError("Something else went wrong"),
            "Unexpected error checking existence",
            True,
        ),
    ],
    ids=[
        "os_error_in_loop",
        "value_error_in_loop",
    ],  # Made ids slightly more descriptive
)
def test_exception_during_loop_returns_none_and_logs(
    mock_fs_configured: Mock,
    caplog: pytest.LogCaptureFixture,
    exception_to_raise: Exception,
    expected_log_keyword: str,
    is_generic_exception_handler: bool,
):
    """
    Test returns None and logs appropriately if fs.exists raises an exception
    during the candidate path generation loop.
    """
    base_path = Path("/target/file.txt")
    first_candidate_path = Path("/target/file-1.txt")

    mock_fs_configured.exists.side_effect = exception_to_raise
    caplog.set_level(logging.ERROR)

    result = find_available_target_path(base_path=base_path, fs=mock_fs_configured)

    assert result is None
    mock_fs_configured.exists.assert_called_once_with(first_candidate_path)

    required_substrings_in_log = [expected_log_keyword, str(first_candidate_path)]
    if not is_generic_exception_handler:  # For logger.error("... %s", e)
        required_substrings_in_log.append(str(exception_to_raise))

    error_log = find_log_record(caplog, logging.ERROR, required_substrings_in_log)
    assert error_log is not None, (
        f"Log for {expected_log_keyword} not found or missing key info."
    )

    if is_generic_exception_handler:  # For logger.exception cases
        assert error_log.exc_info is not None, (
            "exc_info should be set by logger.exception"
        )
        assert isinstance(error_log.exc_info[1], type(exception_to_raise)), (
            "Incorrect exception type in exc_info"
        )
        assert str(exception_to_raise) not in error_log.message, (
            "str(exception) should not be in message for logger.exception"
        )
        assert str(exception_to_raise) in error_log.exc_text, (
            "str(exception) should be in exc_text for logger.exception"
        )
    else:  # For logger.error cases (no exc_info=True by default)
        assert error_log.exc_info is None


def test_invalid_base_path_type_returns_none_and_logs(
    mock_fs_configured: Mock, caplog: pytest.LogCaptureFixture
):
    """
    Test returns None and logs an error if base_path is not a Path-like object
    (e.g., a string that causes AttributeError when .stem, .suffix are accessed).
    """
    invalid_base_path_input = "/this/is/a/string/not/a/path"  # SUT expects Path
    caplog.set_level(logging.ERROR)

    result = find_available_target_path(
        base_path=invalid_base_path_input,  # type: ignore
        fs=mock_fs_configured,
    )

    assert result is None
    error_log = find_log_record(
        caplog,
        logging.ERROR,
        ["Invalid base_path provided", "object has no attribute"],
    )
    assert error_log is not None, (
        "Error log for invalid base_path (AttributeError) not found."
    )
    # Retain the check for the specific attribute name in the log to ensure
    # the original AttributeError detail is propagated.
    assert (
        "stem" in error_log.message
        or "suffix" in error_log.message
        or "parent" in error_log.message
    ), "Log message should hint at the missing Path attribute."

    mock_fs_configured.exists.assert_not_called()
