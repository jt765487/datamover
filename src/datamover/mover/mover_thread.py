import logging
import threading
import time
from queue import Queue, Empty
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class FileMoveThread(threading.Thread):
    """
    Thread that consumes file Paths from a work queue and delegates
    the move operation to a provided callable. This class handles queue
    polling, graceful shutdown, and task bookkeeping, but does not
    implement the business logic of file validation or moving.
    """

    def __init__(
        self,
        *,
        source_queue: Queue[Path],
        process_single: Callable[[Path], None],
        stop_event: threading.Event,
        sleep_func: Callable[[float], None] = time.sleep,
        name: Optional[str] = None,
        poll_interval: float,
    ):
        """
        Args:
            source_queue: Queue of Path items to process.
            process_single: Callable that takes a Path and processes it (returns None).
            stop_event: Event used to signal the thread to stop.
            sleep_func: Function to sleep (injectable for test speed or error backoff).
            name: Optional thread name; defaults to 'FileMoveThread'.
            poll_interval: Time to wait between queue checks (in seconds).
        """
        thread_name = name or "FileMoveThread"
        super().__init__(daemon=True, name=thread_name)

        self.source_queue = source_queue
        self.process_single = process_single
        self.stop_event = stop_event
        self.sleep_func = sleep_func
        self.poll_interval = poll_interval

    def run(self) -> None:
        """
        Main loop: poll the queue, invoke process_single, track counts,
        call task_done, and exit when stop_event is set.
        """
        logger.info("%s starting", self.name)

        while not self.stop_event.is_set():
            try:
                item = self.source_queue.get(block=True, timeout=self.poll_interval)
            except Empty:
                # Queue was empty, loop again to check stop_event
                continue
            except Exception as e:  # Catching broader exceptions during queue.get
                logger.exception("%s: error polling queue: %s", self.name, e)
                # Sleep a bit before retrying to avoid tight loop on persistent queue errors
                self.sleep_func(self.poll_interval)
                continue

            # Got an item; ensure task_done after processing
            try:
                logger.debug("%s dequeued: %s", self.name, item)

                try:
                    self.process_single(item)
                except Exception:
                    # This catches unexpected errors from the process_single callable itself
                    # The process_single_item in the factory already has its own try/except
                    # but another implementation of process_single might not so defensive here
                    logger.exception(
                        "%s: unexpected exception in process_single for item %s",
                        self.name,
                        item,
                    )
            finally:
                try:
                    self.source_queue.task_done()
                except ValueError:  # More specific exception for task_done issues
                    logger.warning(
                        "%s: task_done() called on %s when queue was not expecting it (e.g. already empty or too many calls).",
                        self.name,
                        item,
                    )
                except (
                    Exception
                ) as td_e:  # General catch-all for other task_done() errors
                    logger.warning(
                        "%s: task_done() error for %s: %s", self.name, item, td_e
                    )

        logger.info(
            "%s stopping",
            self.name,
        )

    def stop(self) -> None:
        """
        Signal the thread to stop gracefully by setting the stop_event.
        """
        if not self.stop_event.is_set():
            logger.info("%s stop requested", self.name)
            self.stop_event.set()
        else:
            logger.debug("%s stop already requested", self.name)
