# tests/unit/uploader/test_upload_audit_event.py

import logging
from unittest import mock
from typing import Union, Dict, Any  # Ensure Union is imported

import pytest

from datamover.uploader.upload_audit_event import create_upload_audit_event

MODULE_PATH_FOR_LOGGER = "datamover.uploader.upload_audit_event.audit_logger"

BASE_ARGS = {
    "level": logging.INFO,
    "event_type": "TEST_EVENT",
    "file_name": "test_file.txt",
    "file_size_bytes": 1024,
    "destination_url": "http://example.com/upload",
    "attempt": 1,
    "duration_ms": 123.456,
}


@pytest.fixture
def mock_audit_logger():
    with mock.patch(MODULE_PATH_FOR_LOGGER) as patched_logger:
        yield patched_logger


def test_minimal_event_logged_correctly(mock_audit_logger: mock.MagicMock):
    """Test with only required fields and essential optionals for 'extra'."""
    args: Dict[str, Any] = {  # Added type hint for clarity
        "level": logging.WARNING,
        "event_type": "MINIMAL_UPLOAD",
        "file_name": "minimal.dat",
        "file_size_bytes": 500,
        "destination_url": "sftp://server/path",
        "attempt": 3,
        "duration_ms": 789.123,
    }
    create_upload_audit_event(**args)

    expected_message = "Upload audit: MINIMAL_UPLOAD for 'minimal.dat'"
    expected_extra = {
        "event_type": "MINIMAL_UPLOAD",
        "file_name": "minimal.dat",
        "file_size_bytes": 500,
        "destination_url": "sftp://server/path",
        "attempt": 3,
        "duration_ms": 789,
    }

    mock_audit_logger.log.assert_called_once_with(
        logging.WARNING, expected_message, extra=expected_extra
    )


def test_all_fields_provided_logged_correctly(mock_audit_logger: mock.MagicMock):
    """Test with all optional fields provided."""
    all_args: Dict[str, Any] = {  # Added type hint for clarity
        **BASE_ARGS,
        "status_code": 201,
        "backoff_seconds": 5.8,
        "failure_category": "NETWORK_ERROR",
        "failure_detail": "Timeout connecting to host",
        "exception_type": "TimeoutError",
        "response_text_snippet": "Partial response before timeout...",
    }
    create_upload_audit_event(**all_args)

    expected_message = (
        "Upload audit: TEST_EVENT for 'test_file.txt' "
        "(Status: 201) (Category: NETWORK_ERROR) (Exception: TimeoutError)"
    )
    expected_extra = {
        "event_type": "TEST_EVENT",
        "file_name": "test_file.txt",
        "file_size_bytes": 1024,
        "destination_url": "http://example.com/upload",
        "attempt": 1,
        "duration_ms": 123,
        "status_code": 201,
        "backoff_seconds": 5,
        "failure_category": "NETWORK_ERROR",
        "failure_detail": "Timeout connecting to host",
        "exception_type": "TimeoutError",
        "response_text_snippet": "Partial response before timeout...",
    }

    mock_audit_logger.log.assert_called_once_with(
        logging.INFO, expected_message, extra=expected_extra
    )


def test_optional_fields_as_none(mock_audit_logger: mock.MagicMock):
    args: Dict[str, Any] = {  # Added type hint for clarity
        "level": logging.ERROR,
        "event_type": "NONE_FIELDS",
        "file_name": "none_test.dat",
        "file_size_bytes": None,
        "destination_url": "http://none.land",
        "attempt": 1,
        "duration_ms": None,
    }
    create_upload_audit_event(**args)

    expected_message = "Upload audit: NONE_FIELDS for 'none_test.dat'"
    expected_extra = {
        "event_type": "NONE_FIELDS",
        "file_name": "none_test.dat",
        "file_size_bytes": None,
        "destination_url": "http://none.land",
        "attempt": 1,
        "duration_ms": None,
    }

    mock_audit_logger.log.assert_called_once_with(
        logging.ERROR, expected_message, extra=expected_extra
    )


def test_failure_detail_truncation(mock_audit_logger: mock.MagicMock):
    long_detail = "a" * 300
    args: Dict[str, Any] = {
        **BASE_ARGS,
        "failure_detail": long_detail,
    }  # Added type hint
    create_upload_audit_event(**args)

    mock_audit_logger.log.assert_called_once()
    call_args = mock_audit_logger.log.call_args
    actual_extra = call_args.kwargs.get("extra", {})

    assert "failure_detail" in actual_extra
    assert len(actual_extra["failure_detail"]) == 256
    assert actual_extra["failure_detail"] == "a" * 256


def test_response_text_snippet_truncation(mock_audit_logger: mock.MagicMock):
    long_snippet = "b" * 150
    args: Dict[str, Any] = {
        **BASE_ARGS,
        "response_text_snippet": long_snippet,
    }  # Added type hint
    create_upload_audit_event(**args)

    mock_audit_logger.log.assert_called_once()
    call_args = mock_audit_logger.log.call_args
    actual_extra = call_args.kwargs.get("extra", {})

    assert "response_text_snippet" in actual_extra
    assert len(actual_extra["response_text_snippet"]) == 100
    assert actual_extra["response_text_snippet"] == "b" * 100


@pytest.mark.parametrize(
    "status, category, exception, expected_message_suffix",
    [
        (200, None, None, " (Status: 200)"),
        (None, "CAT_A", None, " (Category: CAT_A)"),
        (None, None, "EX_B", " (Exception: EX_B)"),
        (404, "CAT_C", None, " (Status: 404) (Category: CAT_C)"),
        (500, None, "EX_D", " (Status: 500) (Exception: EX_D)"),
        (None, "CAT_E", "EX_F", " (Category: CAT_E) (Exception: EX_F)"),
        (202, "CAT_G", "EX_H", " (Status: 202) (Category: CAT_G) (Exception: EX_H)"),
        (None, None, None, ""),
    ],
)
def test_message_formatting_variants(
    mock_audit_logger: mock.MagicMock,
    status: Union[int, None],  # CORRECTED HERE
    category: Union[str, None],  # CORRECTED HERE
    exception: Union[str, None],  # CORRECTED HERE
    expected_message_suffix: str,
):
    # Remove keys if their value is None for this test, as they wouldn't be passed if truly absent
    # This is important because the create_upload_audit_event function checks for `is not None`
    # not just truthiness, so passing 'status_code': None is different from not passing 'status_code'.
    # However, for this specific test of message construction, it's fine to pass None
    # as the function handles it. The `del` was more for ensuring the `extra` dict was clean,
    # but the test here focuses on the message.

    # Cleaner way to build args only with non-None optional values for this test:
    current_args = {**BASE_ARGS}
    if status is not None:
        current_args["status_code"] = status
    if category is not None:
        current_args["failure_category"] = category
    if exception is not None:
        current_args["exception_type"] = exception

    create_upload_audit_event(**current_args)

    expected_base_message = (
        f"Upload audit: {BASE_ARGS['event_type']} for '{BASE_ARGS['file_name']}'"
    )
    final_expected_message = expected_base_message + expected_message_suffix

    mock_audit_logger.log.assert_called_once()
    actual_level_called = mock_audit_logger.log.call_args[0][0]
    actual_message_called = mock_audit_logger.log.call_args[0][1]

    assert actual_level_called == BASE_ARGS["level"]
    assert actual_message_called == final_expected_message


def test_duration_ms_is_none_in_extra(mock_audit_logger: mock.MagicMock):
    args: Dict[str, Any] = {**BASE_ARGS, "duration_ms": None}  # Added type hint
    create_upload_audit_event(**args)

    mock_audit_logger.log.assert_called_once()
    actual_extra = mock_audit_logger.log.call_args.kwargs.get("extra", {})
    assert actual_extra.get("duration_ms") is None


def test_backoff_seconds_is_none_if_not_provided(mock_audit_logger: mock.MagicMock):
    # BASE_ARGS does not include backoff_seconds
    create_upload_audit_event(**BASE_ARGS)  # BASE_ARGS is already Dict[str, Any] typed

    mock_audit_logger.log.assert_called_once()
    actual_extra = mock_audit_logger.log.call_args.kwargs.get("extra", {})
    assert "backoff_seconds" not in actual_extra


def test_backoff_seconds_int_conversion(mock_audit_logger: mock.MagicMock):
    args: Dict[str, Any] = {**BASE_ARGS, "backoff_seconds": 10.7}  # Added type hint
    create_upload_audit_event(**args)

    mock_audit_logger.log.assert_called_once()
    actual_extra = mock_audit_logger.log.call_args.kwargs.get("extra", {})
    assert actual_extra.get("backoff_seconds") == 10
