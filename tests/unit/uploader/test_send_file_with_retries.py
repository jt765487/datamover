import logging
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest
import requests

from datamover.protocols import HttpResponse

# Import the SUT
from datamover.uploader.send_file_with_retries import RetryableFileSender

# Log helper
from tests.test_utils.logging_helpers import find_log_record


# Helper to create mock HttpResponse objects
def make_response(code: int, text: str = "") -> MagicMock:
    r = MagicMock(spec=HttpResponse)
    r.status_code = code
    r.text = text
    return r


# --- Test Fixtures specific to this test file ---


@pytest.fixture(autouse=True)
def mock_create_audit_event_for_sender_tests(
    mocker,
):  # Use pytest-mock's mocker fixture
    # mocker.patch returns the MagicMock directly.
    # It will be automatically reset/undone after each test that uses this fixture.
    mock_audit = mocker.patch(
        "datamover.uploader.send_file_with_retries.create_upload_audit_event"
    )
    yield mock_audit  # Yield the mock so it can be injected if a test requests it by name
    # Even though it's autouse, yielding makes it available by name.
    # If no test requests it by name, yield is still fine.


@pytest.fixture
def sender(
    retryable_sender_unit_test_deps: dict,  # This fixture comes from conftest.py
) -> RetryableFileSender:
    """
    Provides an instance of RetryableFileSender, configured using
    the comprehensive 'retryable_sender_unit_test_deps' fixture.
    """
    # retryable_sender_unit_test_deps already contains all keyword arguments
    # needed by RetryableFileSender.__init__
    return RetryableFileSender(**retryable_sender_unit_test_deps)


# --- Test Cases ---


@pytest.mark.parametrize(
    "code,text",
    [
        (101, "Switching Protocols Test"),
        (302, "Redirected"),
        (400, "Bad request"),
        (404, ""),
    ],
)
def test_http_status_dead_letter(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,
    caplog: pytest.LogCaptureFixture,  # Keep for existing log checks
    mock_create_audit_event_for_sender_tests: MagicMock,  # ADDED
    code: int,
    text: str,
):
    caplog.set_level(logging.INFO)  # Keep for existing log checks
    mocked_file_size = 123  # Assume a size for stat mock
    mock_fs_for_sender_unit_tests.exists.return_value = True
    mock_fs_for_sender_unit_tests.stat.return_value = MagicMock(
        st_size=mocked_file_size
    )
    mock_http_client.post.return_value = make_response(code, text)

    expected_dead_letter_dir = retryable_sender_unit_test_deps[
        "dead_letter_destination_dir"
    ]
    expected_dl_path = expected_dead_letter_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_dl_path

    assert sender.send_file(test_file_path_generic) is True

    # Existing log assertions
    substrs = [f"terminal HTTP status ({code})", test_file_path_generic.name]
    if text:
        substrs += ["Response:", text]
    assert find_log_record(caplog, logging.ERROR, substrs) is not None
    # ... (other existing log assertions) ...

    # ADDED: Audit call assertion
    mock_create_audit_event_for_sender_tests.assert_any_call(
        level=logging.ERROR,
        event_type="upload_failure_http_terminal",
        file_name=test_file_path_generic.name,
        file_size_bytes=mocked_file_size,
        destination_url=sender._remote_url,
        attempt=1,
        duration_ms=mock.ANY,  # int
        status_code=code,
        failure_category="HTTP Terminal Error",
        failure_detail=f"Terminal HTTP Error, Status: {code}",  # Corrected
        response_text_snippet=text[:100] if text else None,
    )


def test_send_file_success_moves_to_uploaded_dir(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # To get expected values
    caplog: pytest.LogCaptureFixture,
    mock_create_audit_event_for_sender_tests: MagicMock,
):
    caplog.set_level(logging.INFO)
    mocked_file_size = 456
    mock_fs_for_sender_unit_tests.exists.return_value = True
    mock_http_client.post.return_value = make_response(200, "OK")
    mock_fs_for_sender_unit_tests.stat.return_value = MagicMock(
        st_size=mocked_file_size
    )
    mock_http_client.post.return_value = make_response(200, "OK")

    # Get expected values from the same source as the sender's initialization
    expected_uploaded_dir = retryable_sender_unit_test_deps["uploaded_destination_dir"]
    expected_remote_url = retryable_sender_unit_test_deps["remote_url"]
    expected_request_timeout = retryable_sender_unit_test_deps[
        "request_timeout_seconds"
    ]
    expected_verify_ssl = retryable_sender_unit_test_deps["verify_ssl"]

    expected_uploaded_path = expected_uploaded_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_uploaded_path

    assert sender.send_file(test_file_path_generic) is True

    mock_fs_for_sender_unit_tests.open.assert_called_once_with(
        test_file_path_generic, "rb"
    )
    fh = mock_fs_for_sender_unit_tests.open.return_value.__enter__.return_value
    mock_http_client.post.assert_called_once_with(
        expected_remote_url,
        data=fh,
        headers={
            "x-filename": test_file_path_generic.name,
            "Content-Type": "application/octet-stream",
        },
        timeout=expected_request_timeout,
        verify=expected_verify_ssl,
    )
    mock_safe_file_mover.assert_called_once_with(
        source_path_raw=test_file_path_generic,
        destination_dir=expected_uploaded_dir,
        fs=mock_fs_for_sender_unit_tests,
        expected_source_dir=None,
    )

    assert (
        find_log_record(
            caplog,
            logging.INFO,
            ["Upload SUCCESS", test_file_path_generic.name, "Status: 200"],
        )
        is not None
    )
    assert (
        find_log_record(
            caplog,
            logging.INFO,
            [
                "Successfully moved",
                test_file_path_generic.name,
                "to UPLOADED dir:",
                str(expected_uploaded_path),
            ],
        )
        is not None
    )

    # ADDED: Audit call assertion
    mock_create_audit_event_for_sender_tests.assert_any_call(
        level=logging.INFO,
        event_type="upload_success",
        file_name=test_file_path_generic.name,
        file_size_bytes=mocked_file_size,  # Use the defined mocked_file_size
        destination_url=sender._remote_url,  # Ensure sender has _remote_url or get from deps
        attempt=1,
        duration_ms=mock.ANY,  # int
        status_code=200,
        response_text_snippet="OK"[:100],
    )


def test_network_retry_then_success(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    mock_stop_event: MagicMock,  # Use fixture from conftest
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # For initial_backoff and uploaded_dir
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.WARNING)
    mock_fs_for_sender_unit_tests.exists.return_value = True
    timeout_exc = requests.exceptions.Timeout("t/o")
    mock_http_client.post.side_effect = [timeout_exc, make_response(200, "OK")]

    expected_uploaded_dir = retryable_sender_unit_test_deps["uploaded_destination_dir"]
    expected_uploaded_path = expected_uploaded_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_uploaded_path
    mock_stop_event.wait.return_value = False

    assert sender.send_file(test_file_path_generic) is True
    assert mock_http_client.post.call_count == 2

    expected_backoff = retryable_sender_unit_test_deps["initial_backoff_seconds"]
    mock_stop_event.wait.assert_called_once_with(expected_backoff)
    assert (
        find_log_record(
            caplog,
            logging.WARNING,
            ["Network error", "Retrying", f"{expected_backoff:.1f} sec"],
        )
        is not None
    )


def test_network_retry_then_stop(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    mock_stop_event: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # For initial_backoff
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    mock_fs_for_sender_unit_tests.exists.return_value = True
    mock_http_client.post.side_effect = requests.exceptions.ConnectionError("fail")
    mock_stop_event.wait.return_value = True

    assert sender.send_file(test_file_path_generic) is False

    expected_backoff = retryable_sender_unit_test_deps["initial_backoff_seconds"]
    mock_stop_event.wait.assert_called_once_with(expected_backoff)
    assert (
        find_log_record(caplog, logging.INFO, ["Stop requested during retry backoff"])
        is not None
    )
    mock_safe_file_mover.assert_not_called()


def test_source_vanished_before(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.WARNING)
    mock_fs_for_sender_unit_tests.exists.return_value = False
    assert sender.send_file(test_file_path_generic) is True
    assert (
        find_log_record(
            caplog, logging.WARNING, ["vanished before initial processing attempt"]
        )  # MODIFIED
        is not None
    )


def test_source_vanished_during_open(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.WARNING)
    mock_fs_for_sender_unit_tests.exists.return_value = True
    mock_fs_for_sender_unit_tests.open.side_effect = FileNotFoundError(
        "gone during open"
    )
    assert sender.send_file(test_file_path_generic) is True
    assert (
        find_log_record(
            caplog, logging.WARNING, ["vanished during active send attempt"]
        )  # MODIFIED
        is not None
    )


def test_os_error_on_exists_aborts(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.ERROR)
    mock_fs_for_sender_unit_tests.exists.side_effect = OSError(
        "permission denied on exists"
    )
    assert sender.send_file(test_file_path_generic) is False
    rec = find_log_record(caplog, logging.ERROR, ["OS Error checking source file"])
    assert rec and not rec.exc_info


def test_os_error_on_open_then_dead_letter(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # For dead_letter_dir
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.ERROR)
    mock_fs_for_sender_unit_tests.exists.return_value = True
    err = OSError("disk full during open")
    mock_fs_for_sender_unit_tests.open.side_effect = err

    expected_dead_letter_dir = retryable_sender_unit_test_deps[
        "dead_letter_destination_dir"
    ]
    expected_dl_path = expected_dead_letter_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_dl_path

    assert sender.send_file(test_file_path_generic) is True
    rec = find_log_record(
        caplog, logging.ERROR, ["OS error (OSError) during file open/read for upload"]
    )
    assert rec and rec.exc_info

    mock_safe_file_mover.assert_called_once_with(
        source_path_raw=test_file_path_generic,
        destination_dir=expected_dead_letter_dir,
        fs=mock_fs_for_sender_unit_tests,
        expected_source_dir=None,
    )


def test_request_exception_then_dead_letter(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # For dead_letter_dir
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.ERROR)
    mock_fs_for_sender_unit_tests.exists.return_value = True
    exc = requests.exceptions.InvalidURL("bad url config")
    mock_http_client.post.side_effect = exc

    expected_dead_letter_dir = retryable_sender_unit_test_deps[
        "dead_letter_destination_dir"
    ]
    expected_dl_path = expected_dead_letter_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_dl_path

    assert sender.send_file(test_file_path_generic) is True
    rec = find_log_record(
        caplog, logging.ERROR, ["Non-retryable HTTP request exception (InvalidURL)"]
    )
    assert rec and rec.exc_info


def test_unexpected_exception_then_dead_letter(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # For dead_letter_dir
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.ERROR)
    mock_fs_for_sender_unit_tests.exists.return_value = True
    mock_http_client.post.side_effect = ZeroDivisionError("unexpected oops")

    expected_dead_letter_dir = retryable_sender_unit_test_deps[
        "dead_letter_destination_dir"
    ]
    expected_dl_path = expected_dead_letter_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_dl_path

    assert sender.send_file(test_file_path_generic) is True
    rec = find_log_record(
        caplog,
        logging.ERROR,
        ["Unexpected error (ZeroDivisionError) during send attempt"],
    )
    assert rec and rec.exc_info


def test_stop_event_set_initially_aborts(
    sender: RetryableFileSender,
    mock_stop_event: MagicMock,
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    mock_stop_event.is_set.return_value = True

    assert sender.send_file(test_file_path_generic) is False
    assert (
        find_log_record(
            caplog,
            logging.INFO,
            [
                "Stop signal detected",
                f"process for '{test_file_path_generic.name}' aborted",
            ],
        )
        is not None
    )


# For tests that need to instantiate RetryableFileSender directly with specific parameters,
# we will use the dependencies from retryable_sender_unit_test_deps and override specific values.
def test_backoff_respects_max_then_success(
    retryable_sender_unit_test_deps: dict,  # Base deps
    mock_http_client: MagicMock,  # This will be part of deps, but explicit for clarity
    mock_fs_for_sender_unit_tests: MagicMock,  # Part of deps
    mock_stop_event: MagicMock,  # Part of deps
    mock_safe_file_mover: MagicMock,  # Part of deps
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.WARNING)
    mock_fs_for_sender_unit_tests.exists.return_value = True

    test_initial_backoff = 1.0
    test_max_backoff = 2.0

    # Create a new deps dictionary, overriding specific backoff values
    custom_deps = retryable_sender_unit_test_deps.copy()
    custom_deps["initial_backoff_seconds"] = test_initial_backoff
    custom_deps["max_backoff_seconds"] = test_max_backoff
    # Ensure the correct http_client mock from the fixture is used if it was different in deps
    custom_deps["http_client"] = mock_http_client
    custom_deps["fs"] = mock_fs_for_sender_unit_tests
    custom_deps["stop_event"] = mock_stop_event
    custom_deps["safe_file_mover"] = mock_safe_file_mover

    sender_custom_backoff = RetryableFileSender(**custom_deps)

    to1, to2, to3 = (
        requests.exceptions.Timeout("t1"),
        requests.exceptions.Timeout("t2"),
        requests.exceptions.Timeout("t3"),
    )
    mock_http_client.post.side_effect = [to1, to2, to3, make_response(200, "OK")]

    expected_uploaded_dir = custom_deps["uploaded_destination_dir"]
    expected_uploaded_path = expected_uploaded_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_uploaded_path
    mock_stop_event.wait.return_value = False

    assert sender_custom_backoff.send_file(test_file_path_generic) is True
    waits = [c.args[0] for c in mock_stop_event.wait.call_args_list]
    assert waits == [pytest.approx(1.0), pytest.approx(2.0), pytest.approx(2.0)]


def test_zero_initial_backoff_retry_immediate(
    retryable_sender_unit_test_deps: dict,
    mock_http_client: MagicMock,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_safe_file_mover: MagicMock,
    mock_stop_event: MagicMock,
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.WARNING)

    custom_deps = retryable_sender_unit_test_deps.copy()
    custom_deps["initial_backoff_seconds"] = 0.0
    custom_deps["max_backoff_seconds"] = 0.0  # Typically max_backoff >= initial_backoff
    custom_deps["http_client"] = mock_http_client
    custom_deps["fs"] = mock_fs_for_sender_unit_tests
    custom_deps["stop_event"] = mock_stop_event
    custom_deps["safe_file_mover"] = mock_safe_file_mover

    sender_zero_backoff = RetryableFileSender(**custom_deps)

    mock_fs_for_sender_unit_tests.exists.return_value = True
    to = requests.exceptions.Timeout("t/o zero backoff")
    mock_http_client.post.side_effect = [to, make_response(200, "OK")]

    expected_uploaded_dir = custom_deps["uploaded_destination_dir"]
    expected_uploaded_path = expected_uploaded_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_uploaded_path
    mock_stop_event.wait.return_value = False

    assert sender_zero_backoff.send_file(test_file_path_generic) is True
    mock_stop_event.wait.assert_called_once_with(0.0)
    assert (
        find_log_record(
            caplog,
            logging.WARNING,
            ["Network error", "Retrying in 0.0 sec"],
        )
        is not None
    )


def test_send_file_zero_byte_success(
    sender: RetryableFileSender,  # Uses the general sender fixture
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # For uploaded_dir
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    mock_fs_for_sender_unit_tests.exists.return_value = True
    # Simulate getting file size as 0
    mock_fs_for_sender_unit_tests.stat.return_value = MagicMock(st_size=0)
    mock_http_client.post.return_value = make_response(200, "OK")

    expected_uploaded_dir = retryable_sender_unit_test_deps["uploaded_destination_dir"]
    expected_uploaded_path = expected_uploaded_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_uploaded_path

    assert sender.send_file(test_file_path_generic) is True
    mock_fs_for_sender_unit_tests.open.assert_called_once_with(
        test_file_path_generic, "rb"
    )
    mock_http_client.post.assert_called_once()
    mock_safe_file_mover.assert_called_once()

    assert (
        find_log_record(
            caplog, logging.INFO, ["Upload SUCCESS", test_file_path_generic.name]
        )
        is not None
    )
    assert (
        find_log_record(
            caplog,
            logging.INFO,
            [
                "Successfully moved",
                test_file_path_generic.name,
                "to UPLOADED dir:",
                str(expected_uploaded_path),
            ],
        )
        is not None
    )


# --- Direct tests for _handle_terminal_failure ---
# These tests can use the standard 'sender' fixture as they primarily test
# the behavior of _handle_terminal_failure given the sender's configured state.


def test_handle_terminal_failure_success_move(
    sender: RetryableFileSender,  # Uses standard sender
    mock_safe_file_mover: MagicMock,  # From conftest via sender's deps
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    expected_dl_path = sender._dead_letter_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_dl_path

    result = sender._handle_terminal_failure(
        file_path=test_file_path_generic,
        failure_reason="TestReason",
        response_details="Details",
        exception_info=False,
    )
    assert result is True
    err_rec = find_log_record(
        caplog,
        logging.ERROR,
        ["TestReason", "Response:", "Details", "Moving to DEAD LETTER."],
    )
    assert err_rec and not err_rec.exc_info
    assert (
        find_log_record(
            caplog,
            logging.INFO,
            ["Successfully moved failed file", str(expected_dl_path)],
        )
        is not None
    )


def test_handle_terminal_failure_with_exc_info(
    sender: RetryableFileSender,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    expected_dl_path = sender._dead_letter_dir / test_file_path_generic.name
    mock_safe_file_mover.return_value = expected_dl_path

    result = sender._handle_terminal_failure(
        file_path=test_file_path_generic,
        failure_reason="TestReasonExc",
        exception_info=True,
    )
    assert result is True
    err_rec = find_log_record(caplog, logging.ERROR, ["TestReasonExc"])
    # If logger.error is called with exc_info=True but no actual exception is being handled
    # by a try/except in the SUT at that logging point, exc_info will be (None, None, None).
    # The SUT's _handle_terminal_failure itself doesn't have a try/except when logging for this reason,
    # it just passes the exception_info flag. So, this assertion might need adjustment
    # depending on whether an actual exception is expected to be *active* when this log occurs.
    # For now, assuming the flag just controls if the logger *tries* to find sys.exc_info().
    assert (
        err_rec and err_rec.exc_info is not None
    )  # This checks if the logger recorded *something* for exc_info

    assert (
        find_log_record(
            caplog,
            logging.INFO,
            ["Successfully moved failed file", str(expected_dl_path)],
        )
        is not None
    )


def test_handle_terminal_failure_move_fails(
    sender: RetryableFileSender,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.ERROR)
    mock_safe_file_mover.return_value = None

    result = sender._handle_terminal_failure(
        file_path=test_file_path_generic, failure_reason="FinalFail"
    )
    assert result is False
    assert (
        find_log_record(
            caplog,
            logging.ERROR,
            [
                "FinalFail for file",
                test_file_path_generic.name,
                "Moving to DEAD LETTER.",
            ],
        )
        is not None
    )
    assert (
        find_log_record(
            caplog,
            logging.CRITICAL,
            ["FAILED TO MOVE TO DEAD LETTER", str(test_file_path_generic)],
        )
        is not None
    )


def test_handle_terminal_failure_safe_mover_raises(
    sender: RetryableFileSender,
    mock_safe_file_mover: MagicMock,
    test_file_path_generic: Path,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.ERROR)
    mock_safe_file_mover.side_effect = RuntimeError("mover internal crash")

    with pytest.raises(RuntimeError, match="mover internal crash"):
        sender._handle_terminal_failure(
            file_path=test_file_path_generic, failure_reason="BR Test"
        )
    assert (
        find_log_record(
            caplog,
            logging.ERROR,
            ["BR Test for file", test_file_path_generic.name, "Moving to DEAD LETTER."],
        )
        is not None
    )


def test_send_file_exists_raises_non_oserror(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,  # Use the correct fixture name
    test_file_path_generic: Path,
):
    # This test ensures that non-OSErrors from fs.exists are propagated.
    # The initial fs.stat() call will succeed here, as it's separate.
    # We then cause fs.exists() inside the loop to raise a non-OSError.
    mock_fs_for_sender_unit_tests.stat.return_value = MagicMock(
        st_size=123
    )  # Allow initial stat to pass
    mock_fs_for_sender_unit_tests.exists.side_effect = [
        True,
        ValueError("bad fs call"),
    ]  # First call (initial) True, second (in loop) raises

    with pytest.raises(ValueError, match="bad fs call"):
        sender.send_file(test_file_path_generic)


def test_send_file_http_5xx_retry_then_4xx_terminal(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    mock_stop_event: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # For dead_letter_dir and initial_backoff
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(
        logging.WARNING
    )  # Catches WARNING for retry and ERROR for terminal
    mock_fs_for_sender_unit_tests.exists.return_value = True

    expected_dead_letter_dir = retryable_sender_unit_test_deps[
        "dead_letter_destination_dir"
    ]
    expected_dl_path = expected_dead_letter_dir / test_file_path_generic.name

    mock_http_client.post.side_effect = [
        make_response(503, "Service Unavailable"),
        make_response(403, "Forbidden"),
    ]
    mock_safe_file_mover.return_value = expected_dl_path
    mock_stop_event.wait.return_value = False

    result = sender.send_file(test_file_path_generic)

    assert result is True
    assert mock_http_client.post.call_count == 2

    expected_backoff = retryable_sender_unit_test_deps["initial_backoff_seconds"]
    mock_stop_event.wait.assert_called_once_with(expected_backoff)
    mock_safe_file_mover.assert_called_once_with(
        source_path_raw=test_file_path_generic,
        destination_dir=expected_dead_letter_dir,
        fs=mock_fs_for_sender_unit_tests,
        expected_source_dir=None,
    )
    assert (
        find_log_record(
            caplog,
            logging.WARNING,
            ["Server error", "Status: 503", "Retrying", f"{expected_backoff:.1f} sec"],
        )
        is not None
    )
    assert (
        find_log_record(
            caplog,
            logging.ERROR,
            ["Upload FAILED - terminal HTTP status (403)", test_file_path_generic.name],
        )
        is not None
    )


def test_send_file_http_5xx_retry_then_stop_event(
    sender: RetryableFileSender,
    mock_fs_for_sender_unit_tests: MagicMock,
    mock_http_client: MagicMock,
    mock_safe_file_mover: MagicMock,
    mock_stop_event: MagicMock,
    test_file_path_generic: Path,
    retryable_sender_unit_test_deps: dict,  # For initial_backoff
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)  # Catches INFO stop log, WARNING retry log
    mock_fs_for_sender_unit_tests.exists.return_value = True
    mock_http_client.post.return_value = make_response(502, "Bad Gateway")
    mock_stop_event.wait.return_value = True

    result = sender.send_file(test_file_path_generic)

    assert result is False
    mock_http_client.post.assert_called_once()

    expected_backoff = retryable_sender_unit_test_deps["initial_backoff_seconds"]
    mock_stop_event.wait.assert_called_once_with(expected_backoff)
    mock_safe_file_mover.assert_not_called()
    assert (
        find_log_record(
            caplog,
            logging.INFO,
            ["Stop requested during retry backoff", test_file_path_generic.name],
        )
        is not None
    )
