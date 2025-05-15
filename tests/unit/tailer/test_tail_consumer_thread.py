import logging
import queue
import threading
import time
from typing import Optional
from unittest.mock import MagicMock

import pytest

from datamover.tailer.data_class import TailerQueueEvent, CreatedEvent
from datamover.tailer.tail_consumer_thread import TailConsumerThread
from datamover.tailer.tail_processor import TailProcessor

# Test constants
TEST_POLL_INTERVAL = 0.01  # Faster polling for tests
THREAD_JOIN_TIMEOUT = 0.5  # Timeout for thread join operations


@pytest.fixture
def mock_processor() -> MagicMock:
    """Fixture for a mocked TailProcessor."""
    return MagicMock(spec=TailProcessor)


@pytest.fixture
def event_queue() -> queue.Queue[TailerQueueEvent]:
    """Fixture for a clean event queue."""
    return queue.Queue()


@pytest.fixture
def stop_event() -> threading.Event:
    """Fixture for a clean stop event."""
    return threading.Event()


@pytest.fixture
def consumer_thread_factory(event_queue, stop_event, mock_processor):
    """Factory to create TailConsumerThread instances."""
    threads_started = []  # Keep track of threads to ensure they are joined

    def _factory(
        name: str = "TestConsumer",
        poll_interval: float = TEST_POLL_INTERVAL,
        custom_queue: Optional[queue.Queue[TailerQueueEvent]] = None,
        custom_processor: Optional[TailProcessor] = None,
    ) -> TailConsumerThread:
        thread = TailConsumerThread(
            event_queue=custom_queue or event_queue,
            stop_event=stop_event,  # Use the shared stop_event for simplicity in most tests
            processor=custom_processor or mock_processor,
            name=name,
            poll_interval=poll_interval,
        )
        threads_started.append(thread)
        return thread

    yield _factory

    # Teardown: ensure all created threads are stopped and joined
    for t in threads_started:
        if t.is_alive():
            t.stop()
            t.join(timeout=THREAD_JOIN_TIMEOUT)
            if t.is_alive():
                # This shouldn't happen if stop() and join() work correctly
                print(f"Warning: Thread {t.name} did not terminate cleanly.")


def start_and_stop_thread(
    thread: TailConsumerThread, stop_evt: threading.Event, duration: float = 0.1
):
    """Helper to start, run for a bit, then stop a thread."""
    thread.start()
    time.sleep(duration)  # Let the thread run for a bit
    stop_evt.set()
    thread.join(timeout=THREAD_JOIN_TIMEOUT)
    assert not thread.is_alive(), f"Thread {thread.name} did not stop."


# --- Test Cases ---


def test_thread_initialization(consumer_thread_factory):
    """Test basic initialization of the thread."""
    thread_name = "MyConsumer"
    thread = consumer_thread_factory(name=thread_name)
    assert thread.name == thread_name
    assert thread.daemon is True
    assert thread.poll_interval == TEST_POLL_INTERVAL
    assert not thread.is_alive()


def test_thread_starts_and_stops_cleanly(consumer_thread_factory, stop_event, caplog):
    """Test that the thread starts, logs, and stops cleanly when stop_event is set."""
    thread_name = "CleanStopper"
    thread = consumer_thread_factory(name=thread_name)

    caplog.set_level(logging.INFO)
    thread.start()
    assert thread.is_alive()
    assert f"{thread_name} starting run loop." in caplog.text

    time.sleep(TEST_POLL_INTERVAL * 2)  # Let it poll once or twice

    stop_event.set()
    thread.join(timeout=THREAD_JOIN_TIMEOUT)

    assert not thread.is_alive()
    assert f"{thread_name} stopping." in caplog.text


def test_processes_single_event_successfully(
    consumer_thread_factory, event_queue, mock_processor, stop_event, caplog
):
    """Test processing of a single event."""
    thread = consumer_thread_factory(name="SingleEventProcessor")
    sample_event = CreatedEvent(path="test/file1.txt")
    event_queue.put(sample_event)

    caplog.set_level(logging.DEBUG)
    start_and_stop_thread(thread, stop_event, duration=TEST_POLL_INTERVAL * 5)

    mock_processor.process_event.assert_called_once_with(sample_event)
    assert f"Processing event: {sample_event}" in caplog.text
    assert f"Successfully processed event: {sample_event}" in caplog.text
    assert event_queue.empty(), "Queue should be empty after processing"
    # Check task_done implicitly by queue.empty() and successful join if it were JoinableQueue


def test_handles_empty_queue_and_continues_polling(
    consumer_thread_factory, mock_processor, stop_event
):
    """Test that the thread handles an empty queue by continuing to poll."""
    thread = consumer_thread_factory(name="EmptyQueuePoller")

    start_and_stop_thread(thread, stop_event, duration=TEST_POLL_INTERVAL * 5)
    mock_processor.process_event.assert_not_called()


def test_error_during_queue_get(
    consumer_thread_factory, mock_processor, stop_event, caplog
):
    """Test handling of unexpected errors from queue.get()."""
    mock_q = MagicMock(spec=queue.Queue)
    mock_q.get.side_effect = RuntimeError("Queue access failed!")
    # task_done should not be called if .get() fails before retrieving an item
    mock_q.task_done = MagicMock()

    thread = consumer_thread_factory(name="QueueGetError", custom_queue=mock_q)
    caplog.set_level(logging.ERROR)

    start_and_stop_thread(thread, stop_event, duration=TEST_POLL_INTERVAL * 5)

    assert mock_q.get.call_count > 0
    mock_processor.process_event.assert_not_called()
    mock_q.task_done.assert_not_called()
    assert "Unexpected error polling event queue" in caplog.text
    assert "RuntimeError: Queue access failed!" in caplog.text  # Exception info


def test_error_during_queue_task_done(
    consumer_thread_factory, event_queue, mock_processor, stop_event, caplog
):
    """Test handling of errors raised by event_queue.task_done()."""
    thread = consumer_thread_factory(name="TaskDoneError")
    sample_event = CreatedEvent(path="test/task_done_error.txt")
    event_queue.put(sample_event)

    # Mock task_done on the real queue to raise an error
    event_queue.task_done = MagicMock(side_effect=ValueError("task_done failed!"))

    caplog.set_level(logging.WARNING)
    start_and_stop_thread(thread, stop_event, duration=TEST_POLL_INTERVAL * 5)

    mock_processor.process_event.assert_called_once_with(sample_event)
    event_queue.task_done.assert_called_once()  # Check it was called
    assert f"Error calling task_done() for event '{sample_event}'" in caplog.text
    assert "task_done failed!" in caplog.text  # The error message


def test_stop_method_idempotency(consumer_thread_factory, stop_event, caplog):
    """Test that calling stop() multiple times is handled gracefully."""
    thread_name = "IdempotentStop"
    thread = consumer_thread_factory(name=thread_name)

    # Set caplog to DEBUG to capture the "Stop already requested." message
    caplog.set_level(logging.DEBUG)

    thread.start()
    # It's good practice to ensure the thread has actually started its run loop
    # A short sleep is okay, or a more robust sync mechanism if needed for complex tests.
    time.sleep(
        TEST_POLL_INTERVAL * 2
    )  # Give it a moment to enter run loop and log start

    # --- First stop call ---
    caplog.clear()  # Clear previous logs (like "starting run loop") before checking specific stop logs
    thread.stop()

    # Check for the first log message
    first_stop_logged = any(
        record.levelname == "INFO"
        and f"{thread_name}: Stop requested." in record.message
        for record in caplog.records
    )
    assert first_stop_logged, "Expected 'Stop requested.' INFO log not found."

    # --- Second stop call ---
    caplog.clear()  # Clear logs from the first stop call
    thread.stop()

    # Check for the second log message
    second_stop_logged = any(
        record.levelname == "DEBUG"
        and f"{thread_name}: Stop already requested." in record.message
        for record in caplog.records
    )
    assert second_stop_logged, "Expected 'Stop already requested.' DEBUG log not found."

    # --- Cleanup ---
    # Ensure event is set for actual loop termination (if not already set by a successful stop)
    if not stop_event.is_set():  # Should be set by the first successful stop()
        stop_event.set()

    thread.join(timeout=THREAD_JOIN_TIMEOUT)
    assert not thread.is_alive(), f"Thread {thread_name} did not stop."


def test_processes_multiple_events(
    consumer_thread_factory, event_queue, mock_processor, stop_event
):
    """Test processing of multiple events sequentially."""
    thread = consumer_thread_factory(name="MultiEventProcessor")
    event1 = CreatedEvent(path="test/file1.txt")
    event2 = CreatedEvent(path="test/file2.txt")

    event_queue.put(event1)
    event_queue.put(event2)

    start_and_stop_thread(thread, stop_event, duration=TEST_POLL_INTERVAL * 10)

    assert mock_processor.process_event.call_count == 2
    mock_processor.process_event.assert_any_call(event1)
    mock_processor.process_event.assert_any_call(event2)
    assert event_queue.empty()


def test_thread_stops_if_event_set_before_run_loop(
    consumer_thread_factory, stop_event, caplog
):
    thread_name = "PreStopper"
    thread = consumer_thread_factory(name=thread_name)
    caplog.set_level(
        logging.INFO
    )  # Or DEBUG if you want to see poll attempts that get queue.Empty

    stop_event.set()  # Set stop event BEFORE starting the thread
    thread.start()
    thread.join(timeout=THREAD_JOIN_TIMEOUT)  # Should exit quickly

    assert not thread.is_alive(), f"Thread {thread_name} did not stop."
    # Check logs to ensure it started and then stopped
    assert f"{thread_name} starting run loop." in caplog.text
    assert f"{thread_name} stopping." in caplog.text
    # No events should have been processed
    # mock_processor (if passed to factory) should not have process_event called.


def test_error_during_processor_process_event(
    consumer_thread_factory, event_queue, mock_processor, stop_event, caplog
):
    thread = consumer_thread_factory(name="ProcessorError")
    sample_event = CreatedEvent(path="test/error_file.txt")
    mock_processor.process_event.side_effect = ValueError("Processing failed!")
    event_queue.put(sample_event)

    original_task_done = event_queue.task_done
    event_queue.task_done = MagicMock(wraps=original_task_done)

    caplog.set_level(logging.ERROR)
    # start_and_stop_thread runs for TEST_POLL_INTERVAL * 5 (e.g., 0.05s)
    # The SUT will now internally sleep for TEST_POLL_INTERVAL (0.01s) if process_event fails.
    # This should fit well within the existing test's duration.
    start_and_stop_thread(thread, stop_event, duration=TEST_POLL_INTERVAL * 5)

    # These assertions should remain valid:
    mock_processor.process_event.assert_called_once_with(sample_event)
    event_queue.task_done.assert_called_once()
    assert f"Error processing event '{sample_event}'" in caplog.text
    assert "ValueError: Processing failed!" in caplog.text
