import logging
import queue  # For queue.Full and queue.Queue type
from unittest.mock import MagicMock

import pytest

from datamover.queues.queue_functions import (
    safe_put,
    QueueFullOnPut,
    QueuePutFailed,
    QueuePutError,
)
from tests.test_utils.logging_helpers import find_log_record


# --- Test Cases ---


def test_safe_put_successful_blocking_default_timeout(caplog: pytest.LogCaptureFixture):
    """
    Tests successful put with default timeout (block=True, timeout=None).
    Verifies item is put and debug log is generated.
    """
    caplog.set_level(logging.DEBUG)
    mock_queue = MagicMock(spec=queue.Queue)
    item_to_put = "test_item_blocking"
    queue_name = "BlockingQueue"

    safe_put(
        item=item_to_put, output_queue=mock_queue, queue_name=queue_name
    )  # timeout=None is default

    mock_queue.put.assert_called_once_with(item_to_put, block=True, timeout=None)

    log_entry = find_log_record(
        caplog,
        logging.DEBUG,
        [f"Queued item for '{queue_name}' queue: {item_to_put}", "(Timeout: None)"],
    )
    assert log_entry is not None, "Debug log for successful blocking put not found."


def test_safe_put_successful_timed_timeout(caplog: pytest.LogCaptureFixture):
    """
    Tests successful put with a positive timeout (block=True, timeout > 0).
    Verifies item is put and debug log is generated.
    """
    caplog.set_level(logging.DEBUG)
    mock_queue = MagicMock(spec=queue.Queue)
    item_to_put = "test_item_timed"
    queue_name = "TimedQueue"
    timeout_val = 1.0

    safe_put(
        item=item_to_put,
        output_queue=mock_queue,
        queue_name=queue_name,
        timeout=timeout_val,
    )

    mock_queue.put.assert_called_once_with(item_to_put, block=True, timeout=timeout_val)
    log_entry = find_log_record(
        caplog,
        logging.DEBUG,
        [
            f"Queued item for '{queue_name}' queue: {item_to_put}",
            f"(Timeout: {timeout_val})",
        ],
    )
    assert log_entry is not None, "Debug log for successful timed put not found."


def test_safe_put_successful_non_blocking_timeout(caplog: pytest.LogCaptureFixture):
    """
    Tests successful put with a non-positive timeout (block=True, timeout <= 0),
    effectively making it non-blocking.
    Verifies item is put and debug log is generated.
    """
    caplog.set_level(logging.DEBUG)
    mock_queue = MagicMock(spec=queue.Queue)
    item_to_put = "test_item_non_blocking"
    queue_name = "NonBlockingQueue"
    timeout_val = 0.0

    safe_put(
        item=item_to_put,
        output_queue=mock_queue,
        queue_name=queue_name,
        timeout=timeout_val,
    )

    mock_queue.put.assert_called_once_with(item_to_put, block=True, timeout=timeout_val)
    log_entry = find_log_record(
        caplog,
        logging.DEBUG,
        [
            f"Queued item for '{queue_name}' queue: {item_to_put}",
            f"(Timeout: {timeout_val})",
        ],
    )
    assert log_entry is not None, "Debug log for successful non-blocking put not found."


def test_safe_put_queue_full_on_timed_put(caplog: pytest.LogCaptureFixture):
    """
    Tests QueueFullOnPut exception when a timed put (timeout > 0) encounters
    a full queue (mocked by raising queue.Full).
    Verifies warning log and correct exception.
    """
    caplog.set_level(logging.WARNING)
    mock_queue = MagicMock(spec=queue.Queue)
    item_to_put = "item_for_full_queue_timed"
    queue_name = "FullTimedQueue"
    timeout_val = 0.5

    mock_queue.put.side_effect = queue.Full

    with pytest.raises(QueueFullOnPut) as exc_info:
        safe_put(
            item=item_to_put,
            output_queue=mock_queue,
            queue_name=queue_name,
            timeout=timeout_val,
        )

    mock_queue.put.assert_called_once_with(item_to_put, block=True, timeout=timeout_val)
    assert exc_info.value.__cause__ is None  # Check 'from None'

    log_entry = find_log_record(
        caplog,
        logging.WARNING,
        [
            f"Queue full condition encountered for '{queue_name}' queue",
            f"Item: {item_to_put}",
            f"(Timeout: {timeout_val})",
            "Raising QueueFullOnPut",
        ],
    )
    assert log_entry is not None, "Warning log for QueueFullOnPut (timed) not found."


def test_safe_put_queue_full_on_non_blocking_put(caplog: pytest.LogCaptureFixture):
    """
    Tests QueueFullOnPut exception when a non-blocking put (timeout <= 0)
    encounters a full queue.
    Verifies warning log and correct exception.
    """
    caplog.set_level(logging.WARNING)
    mock_queue = MagicMock(spec=queue.Queue)
    item_to_put = "item_for_full_queue_non_blocking"
    queue_name = "FullNonBlockingQueue"
    timeout_val = 0

    mock_queue.put.side_effect = queue.Full

    with pytest.raises(QueueFullOnPut) as exc_info:
        safe_put(
            item=item_to_put,
            output_queue=mock_queue,
            queue_name=queue_name,
            timeout=timeout_val,
        )

    mock_queue.put.assert_called_once_with(item_to_put, block=True, timeout=timeout_val)
    assert exc_info.value.__cause__ is None
    log_entry = find_log_record(
        caplog,
        logging.WARNING,
        [
            f"Queue full condition encountered for '{queue_name}' queue",
            f"Item: {item_to_put}",
            f"(Timeout: {timeout_val})",
            "Raising QueueFullOnPut",
        ],
    )
    assert log_entry is not None, (
        "Warning log for QueueFullOnPut (non-blocking) not found."
    )


def test_safe_put_queue_full_on_blocking_put_default_timeout(
    caplog: pytest.LogCaptureFixture,
):
    """
    Tests QueueFullOnPut when a blocking put (timeout=None) encounters
    a full queue (mocked).
    """
    caplog.set_level(logging.WARNING)
    mock_queue = MagicMock(spec=queue.Queue)
    item_to_put = "item_for_full_queue_blocking"
    queue_name = "FullBlockingQueue"
    timeout_val = None

    mock_queue.put.side_effect = queue.Full

    with pytest.raises(QueueFullOnPut) as exc_info:
        safe_put(
            item=item_to_put,
            output_queue=mock_queue,
            queue_name=queue_name,
            timeout=timeout_val,
        )

    mock_queue.put.assert_called_once_with(item_to_put, block=True, timeout=timeout_val)
    assert exc_info.value.__cause__ is None
    log_entry = find_log_record(
        caplog,
        logging.WARNING,
        [
            f"Queue full condition encountered for '{queue_name}' queue",
            f"Item: {item_to_put}",
            "(Timeout: None)",
            "Raising QueueFullOnPut",
        ],
    )
    assert log_entry is not None, "Warning log for QueueFullOnPut (blocking) not found."


def test_safe_put_unexpected_exception_during_put(caplog: pytest.LogCaptureFixture):
    """
    Tests QueuePutFailed exception when queue.put() raises an unexpected error.
    Verifies exception log, correct custom exception, and original cause.
    """
    caplog.set_level(logging.ERROR)
    mock_queue = MagicMock(spec=queue.Queue)
    item_to_put = "item_for_unexpected_error"
    queue_name = "ErrorQueue"
    timeout_val = 1.0

    original_exception = RuntimeError("Simulated underlying storage failure")
    mock_queue.put.side_effect = original_exception

    with pytest.raises(QueuePutFailed) as exc_info:
        safe_put(
            item=item_to_put,
            output_queue=mock_queue,
            queue_name=queue_name,
            timeout=timeout_val,
        )

    mock_queue.put.assert_called_once_with(item_to_put, block=True, timeout=timeout_val)
    assert exc_info.value.__cause__ is original_exception

    log_entry = find_log_record(
        caplog,
        logging.ERROR,
        [
            f"Unexpected error during put operation for '{queue_name}' queue",
            f"Item: {item_to_put}",
            f"(Timeout: {timeout_val})",
            "Raising QueuePutFailed",
        ],
    )
    assert log_entry is not None, "Error log for QueuePutFailed not found."
    # Verify exc_info is populated by logger.exception
    assert log_entry.exc_info is not None
    assert log_entry.exc_info[0] is RuntimeError  # Check type of original exception
    assert (
        log_entry.exc_info[1] is original_exception
    )  # Check instance of original exception


def test_queue_put_error_is_base_for_specific_errors():
    """
    Verifies that QueueFullOnPut and QueuePutFailed inherit from QueuePutError.
    """
    assert issubclass(QueueFullOnPut, QueuePutError)
    assert issubclass(QueuePutFailed, QueuePutError)

    try:
        raise QueueFullOnPut()
    except QueuePutError:
        pass  # Expected
    except Exception:  # pragma: no cover
        pytest.fail("QueueFullOnPut should be caught by QueuePutError")

    try:
        raise QueuePutFailed()
    except QueuePutError:
        pass  # Expected
    except Exception:  # pragma: no cover
        pytest.fail("QueuePutFailed should be caught by QueuePutError")
