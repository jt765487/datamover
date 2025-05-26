import logging
import queue
from typing import Any, Optional

logger = logging.getLogger(__name__)


class QueuePutError(Exception):
    """Base exception indicating a failure during the safe_put operation."""

    pass


class QueueFullOnPut(QueuePutError):
    """Raised by safe_put when the queue is full (timeout expired or non-blocking)."""

    pass


class QueuePutFailed(QueuePutError):
    """Raised by safe_put for unexpected errors during the put operation."""

    pass


def safe_put(
    item: Any,
    output_queue: queue.Queue[Any],
    queue_name: str = "Unnamed Queue",
    timeout: Optional[float] = None,
) -> None:
    """
    Puts an "item" onto the queue, raising simple custom exceptions on failure.

    Controls blocking behavior via the timeout parameter:
    - timeout=None (default): Blocks indefinitely.
    - timeout > 0: Blocks for at most 'timeout' seconds. Raises QueueFullOnPut if timeout expires.
    - Timeout <= 0: Non-blocking. Raises QueueFullOnPut immediately if queue is full.

    Args:
        item: The object to enqueue.
        output_queue: The queue instance to put the object onto.
        queue_name: A descriptive name for the queue (used for logging).
        timeout: Controls blocking: None=infinite, >0=timed, <=0=non-blocking.

    Raises:
        QueueFullOnPut: If the queue is full when timeout expires or for non-blocking put.
        QueuePutFailed: For any other unexpected exception during the put operation.
                        Check logs for specific context and original exception traceback.

    Returns:
        None. Success is indicated by the function returning normally.
    """
    try:
        output_queue.put(item, block=True, timeout=timeout)
        logger.debug(
            "Queued item for '%s' queue: %s (Timeout: %s)", queue_name, item, timeout
        )

    except queue.Full:
        # Log the context here since the exception itself won't carry it.
        logger.warning(
            "Queue full condition encountered for '%s' queue. Item: %s (Timeout: %s). Raising QueueFullOnPut.",
            queue_name,
            item,
            timeout,
        )

        raise QueueFullOnPut() from None

    except Exception as e:
        # Log the context here since the exception itself won't carry it.
        logger.exception(
            "Unexpected error during put operation for '%s' queue. Item: %s (Timeout: %s). Raising QueuePutFailed.",
            queue_name,
            item,
            timeout,
        )

        raise QueuePutFailed() from e
