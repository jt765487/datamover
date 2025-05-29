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


@pytest.mark.parametrize(
    "timeout_val, queue_name, item_to_put, expected_timeout_str",
    [
        (0.5, "FullTimedQueue", "item_for_full_queue_timed", "(Timeout: 0.5)"),
        (0, "FullNonBlockingQueue", "item_for_full_queue_non_blocking", "(Timeout: 0)"),
        (
            None,
            "FullBlockingQueue",
            "item_for_full_queue_blocking",
            "(Timeout: None)",
        ),
    ],
)
def test_safe_put_queue_full_raises(
    caplog: pytest.LogCaptureFixture,
    timeout_val,
    queue_name,
    item_to_put,
    expected_timeout_str,
):
    """
    Parametrized test for QueueFullOnPut when queue.put() raises queue.Full
    under various timeout configurations.
    """
    caplog.set_level(logging.WARNING)
    mock_queue = MagicMock(spec=queue.Queue)
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
            expected_timeout_str,
            "Raising QueueFullOnPut",
        ],
    )
    assert log_entry is not None, (
        f"Warning log for QueueFullOnPut ({queue_name}) not found."
    )


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
    assert log_entry.exc_info is not None
    exc_type, exc_value, _ = log_entry.exc_info
    assert exc_type is RuntimeError
    assert exc_value is original_exception


def test_queue_put_error_is_base_for_specific_errors():
    """
    Verifies that QueueFullOnPut and QueuePutFailed inherit from QueuePutError.
    """
    assert issubclass(QueueFullOnPut, QueuePutError)
    assert issubclass(QueuePutFailed, QueuePutError)

    try:
        raise QueueFullOnPut()
    except QueuePutError:
        pass
    except Exception:  # pragma: no cover
        pytest.fail("QueueFullOnPut should be caught by QueuePutError")

    try:
        raise QueuePutFailed()
    except QueuePutError:
        pass
    except Exception:  # pragma: no cover
        pytest.fail("QueuePutFailed should be caught by QueuePutError")
