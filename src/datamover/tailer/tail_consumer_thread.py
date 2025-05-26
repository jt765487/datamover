import logging
import queue
import threading
import time

from datamover.tailer.data_class import TailerQueueEvent
from datamover.tailer.tail_processor import TailProcessor

logger = logging.getLogger(__name__)


class TailConsumerThread(threading.Thread):
    """
    Robust thread that consumes event dataclass objects from a queue
    and delegates them to a TailProcessor.
    """

    def __init__(
        self,
        *,
        event_queue: queue.Queue[TailerQueueEvent],
        stop_event: threading.Event,
        processor: TailProcessor,
        name: str,
        poll_interval: float,
    ) -> None:
        super().__init__(daemon=True, name=name)

        self.event_queue: queue.Queue[TailerQueueEvent] = event_queue
        self.stop_event: threading.Event = stop_event
        self.processor: TailProcessor = processor
        self.poll_interval: float = poll_interval

        logger.debug(
            "%s initialized with poll_interval=%.2f s", self.name, self.poll_interval
        )

    def run(self) -> None:
        logger.info("%s starting run loop.", self.name)
        while not self.stop_event.is_set():
            try:
                event_object: TailerQueueEvent = self.event_queue.get(
                    timeout=self.poll_interval
                )
            except queue.Empty:
                continue
            except Exception:
                logger.exception("%s: Unexpected error polling event queue", self.name)
                continue

            try:
                logger.debug("%s: Processing event: %s", self.name, event_object)
                self.processor.process_event(event_object)
                logger.debug(
                    "%s: Successfully processed event: %s", self.name, event_object
                )
            except Exception:
                logger.exception(
                    "%s: Error processing event '%s'",
                    self.name,
                    event_object,
                )
                if not self.stop_event.is_set():
                    # Only sleep if we're not already trying to stop, to avoid prolonging shutdown.
                    time.sleep(self.poll_interval)  # Sleep to avoid busy loop on error.
            finally:
                try:
                    self.event_queue.task_done()
                except (ValueError, RuntimeError) as td_e:
                    logger.warning(
                        "%s: Error calling task_done() for event '%s': %s",
                        self.name,
                        event_object,
                        td_e,  # This is a warning, not exception, so include error string
                    )
        logger.info("%s stopping.", self.name)

    def stop(self) -> None:
        if not self.stop_event.is_set():
            logger.info("%s: Stop requested.", self.name)
            self.stop_event.set()
        else:
            logger.debug("%s: Stop already requested.", self.name)
