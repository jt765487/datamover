import logging
import threading
import time
from pathlib import Path
from queue import Queue, Empty
from typing import Callable, Generator, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from datamover.mover.mover_thread import FileMoveThread

# Get the actual logger instance from the module under test
from datamover.mover.mover_thread import logger as mover_thread_logger
from tests.test_utils.logging_helpers import find_log_record


@pytest.fixture
def mock_source_queue(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock(spec=Queue)


@pytest.fixture
def mock_process_single(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock(spec=Callable[[Path], None])


@pytest.fixture
def real_stop_event() -> threading.Event:
    """Provides a real threading.Event, cleared after test if needed (though typically thread joins)."""
    return threading.Event()


@pytest.fixture
def mock_sleep(
    mocker: MockerFixture,
) -> MagicMock:  # Renamed from mock_sleep_func for brevity
    return mocker.MagicMock(spec=Callable[[float], None])


@pytest.fixture
def thread_name() -> str:
    return "TestMoverThreadPytest"


@pytest.fixture
def test_poll_interval() -> float:
    return 0.01


@pytest.fixture
def file_move_thread(
    mock_source_queue: MagicMock,
    mock_process_single: MagicMock,
    real_stop_event: threading.Event,
    mock_sleep: MagicMock,
    thread_name: str,
    test_poll_interval: float,
) -> Generator[FileMoveThread, None, None]:
    """
    Provides an instance of FileMoveThread, but DOES NOT start it.
    Manages cleanup by setting stop_event and joining if the thread was started by a test.
    """
    thread = FileMoveThread(
        source_queue=mock_source_queue,
        process_single=mock_process_single,
        stop_event=real_stop_event,
        sleep_func=mock_sleep,
        name=thread_name,
        poll_interval=test_poll_interval,
    )
    yield thread
    # Cleanup: if the test started the thread, ensure it's stopped and joined.
    if thread.is_alive():
        if not real_stop_event.is_set():  # pragma: no cover
            real_stop_event.set()
        thread.join(timeout=test_poll_interval * 50)
        if thread.is_alive():  # pragma: no cover
            print(
                f"Warning: Thread {thread.name} did not terminate cleanly in fixture teardown."
            )


class TestFileMoveThread:
    def test_initialization(
        self,
        file_move_thread: FileMoveThread,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        mock_sleep: MagicMock,
        thread_name: str,
        test_poll_interval: float,
    ):
        assert file_move_thread.source_queue == mock_source_queue
        assert file_move_thread.process_single == mock_process_single
        assert file_move_thread.stop_event == real_stop_event
        assert file_move_thread.sleep_func == mock_sleep
        assert file_move_thread.name == thread_name
        assert file_move_thread.poll_interval == test_poll_interval
        assert file_move_thread.daemon, "Thread should be a daemon thread."

    def test_initialization_default_name(
        self,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        mock_sleep: MagicMock,
        # poll_interval is required, so use the fixture
        test_poll_interval: float,
    ):
        thread = FileMoveThread(
            source_queue=mock_source_queue,
            process_single=mock_process_single,
            stop_event=real_stop_event,
            sleep_func=mock_sleep,
            poll_interval=test_poll_interval,
            # name is omitted
        )
        assert thread.name == "FileMoveThread", (
            "Thread name should default to FileMoveThread."
        )
        assert thread.poll_interval == test_poll_interval

    def test_run_processes_item_successfully(
        self,
        file_move_thread: FileMoveThread,  # The fixture instance
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,  # To control the loop from side_effect
        test_poll_interval: float,
        thread_name: str,
        caplog: pytest.LogCaptureFixture,
    ):
        test_path = Path("test_file.txt")
        call_count = 0

        def mock_get_side_effect(block, timeout):
            assert timeout == test_poll_interval, "Queue.get timeout incorrect"
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return test_path
            else:
                real_stop_event.set()  # Signal thread to stop
                raise Empty

        mock_source_queue.get.side_effect = mock_get_side_effect

        with caplog.at_level(logging.DEBUG, logger=mover_thread_logger.name):
            file_move_thread.start()
            file_move_thread.join(
                timeout=test_poll_interval * 100
            )  # Increased for safety

        assert not file_move_thread.is_alive(), "Thread did not terminate"

        assert find_log_record(caplog, logging.INFO, [f"{thread_name} starting"])
        assert find_log_record(
            caplog, logging.DEBUG, [f"{thread_name} dequeued: {test_path}"]
        )
        assert find_log_record(caplog, logging.INFO, [f"{thread_name} stopping"])

        mock_process_single.assert_called_once_with(test_path)
        mock_source_queue.task_done.assert_called_once()
        mock_source_queue.get.assert_any_call(block=True, timeout=test_poll_interval)

        # Ensure our mock sleep function on the thread was never invoked
        sleep_fn = cast(MagicMock, file_move_thread.sleep_func)
        sleep_fn.assert_not_called()

    def test_run_processes_multiple_items(
        self,
        file_move_thread: FileMoveThread,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        test_poll_interval: float,
    ) -> None:
        paths = [Path("file1.txt"), Path("file2.txt")]
        items_iter = iter(paths)

        def mock_get_side_effect(block: bool, timeout: float) -> Path:
            assert timeout == test_poll_interval
            try:
                return next(items_iter)
            except StopIteration:
                real_stop_event.set()
                raise Empty

        mock_source_queue.get.side_effect = mock_get_side_effect

        file_move_thread.start()
        file_move_thread.join(timeout=test_poll_interval * 100)
        assert not file_move_thread.is_alive(), "Thread did not terminate"

        # … rest of your assertions …

        # Cast the sleep_func back to MagicMock so mypy knows it has assert_not_called()
        from typing import cast
        from unittest.mock import MagicMock

        sleep_fn = cast(MagicMock, file_move_thread.sleep_func)
        sleep_fn.assert_not_called()

    def test_run_handles_queue_empty_and_continues_until_stop(
        self,
        file_move_thread: FileMoveThread,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        test_poll_interval: float,
    ):
        call_count = 0

        def mock_get_side_effect(block, timeout):
            assert timeout == test_poll_interval
            nonlocal call_count
            call_count += 1
            if call_count > 2:  # After 2 Empty exceptions, set stop_event
                real_stop_event.set()
            raise Empty

        mock_source_queue.get.side_effect = mock_get_side_effect

        file_move_thread.start()
        file_move_thread.join(timeout=test_poll_interval * 100)  # Adjusted timeout
        assert not file_move_thread.is_alive(), "Thread did not terminate"

        assert mock_source_queue.get.call_count >= 3
        mock_process_single.assert_not_called()
        mock_source_queue.task_done.assert_not_called()

        # Cast the sleep_func back to MagicMock so mypy knows assert_not_called exists
        sleep_fn = cast(MagicMock, file_move_thread.sleep_func)
        sleep_fn.assert_not_called()

    def test_run_handles_queue_get_exception_and_sleeps(
        self,
        file_move_thread: FileMoveThread,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        test_poll_interval: float,
        thread_name: str,
        caplog: pytest.LogCaptureFixture,
    ):
        queue_error = ValueError("Simulated persistent queue error")
        call_count = 0

        def mock_get_side_effect(block, timeout):
            assert timeout == test_poll_interval
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise queue_error
            else:
                real_stop_event.set()
                raise Empty

        mock_source_queue.get.side_effect = mock_get_side_effect

        with caplog.at_level(logging.ERROR, logger=mover_thread_logger.name):
            file_move_thread.start()
            file_move_thread.join(timeout=test_poll_interval * 100)
        assert not file_move_thread.is_alive(), "Thread did not terminate"

        log_entry = find_log_record(
            caplog,
            logging.ERROR,
            [f"{thread_name}: error polling queue", str(queue_error)],
        )
        assert log_entry is not None, f"Log not found. Logs: {caplog.text}"
        if log_entry:  # Check exc_info if log_entry was found
            assert log_entry.exc_info is not None
            assert log_entry.exc_info[0] is ValueError

        # Cast the sleep_func back to MagicMock so mypy knows assert_not_called exists
        sleep_fn = cast(MagicMock, file_move_thread.sleep_func)
        sleep_fn.assert_called_once_with(test_poll_interval)

        mock_process_single.assert_not_called()
        mock_source_queue.task_done.assert_not_called()

    def test_run_process_single_raises_exception(
        self,
        file_move_thread: FileMoveThread,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        test_poll_interval: float,
        thread_name: str,
        caplog: pytest.LogCaptureFixture,
    ):
        test_path = Path("bad_file.txt")
        process_error = RuntimeError("Simulated error during processing")
        mock_process_single.side_effect = process_error
        items_returned_count = 0

        def mock_get_side_effect(block, timeout):
            assert timeout == test_poll_interval
            nonlocal items_returned_count
            if items_returned_count == 0:
                items_returned_count += 1
                return test_path
            else:
                real_stop_event.set()
                raise Empty

        mock_source_queue.get.side_effect = mock_get_side_effect

        with caplog.at_level(logging.ERROR, logger=mover_thread_logger.name):
            file_move_thread.start()
            file_move_thread.join(timeout=test_poll_interval * 100)
        assert not file_move_thread.is_alive(), "Thread did not terminate"

        log_entry = find_log_record(
            caplog,
            logging.ERROR,
            [
                f"{thread_name}: unexpected exception in process_single for item {test_path}"
            ],
        )
        assert log_entry is not None, f"Log not found. Logs: {caplog.text}"
        if log_entry:
            assert log_entry.exc_info is not None
            assert log_entry.exc_info[0] is RuntimeError

        mock_process_single.assert_called_once_with(test_path)
        mock_source_queue.task_done.assert_called_once()

        # Cast the sleep_func back to MagicMock so mypy knows assert_not_called exists
        sleep_fn = cast(MagicMock, file_move_thread.sleep_func)
        sleep_fn.assert_not_called()

    def test_run_task_done_raises_value_error(
        self,
        file_move_thread: FileMoveThread,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        test_poll_interval: float,
        thread_name: str,
        caplog: pytest.LogCaptureFixture,
    ):
        test_path = Path("another_file.txt")
        task_done_error = ValueError("task_done() called inappropriately")
        mock_source_queue.task_done.side_effect = task_done_error
        items_returned_count = 0

        def mock_get_side_effect(block, timeout):
            assert timeout == test_poll_interval
            nonlocal items_returned_count
            if items_returned_count == 0:
                items_returned_count += 1
                return test_path
            else:
                real_stop_event.set()
                raise Empty

        mock_source_queue.get.side_effect = mock_get_side_effect

        with caplog.at_level(logging.WARNING, logger=mover_thread_logger.name):
            file_move_thread.start()
            file_move_thread.join(timeout=test_poll_interval * 100)
        assert not file_move_thread.is_alive(), "Thread did not terminate"

        assert find_log_record(
            caplog,
            logging.WARNING,
            [
                f"{thread_name}: task_done() called on {test_path} when queue was not expecting it"
            ],
        ), f"Log not found. Logs: {caplog.text}"
        mock_process_single.assert_called_once_with(test_path)
        mock_source_queue.task_done.assert_called_once()

        # Cast the sleep_func back to MagicMock so mypy knows assert_not_called exists
        sleep_fn = cast(MagicMock, file_move_thread.sleep_func)
        sleep_fn.assert_not_called()

    def test_run_task_done_raises_other_exception(
        self,
        file_move_thread: FileMoveThread,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        test_poll_interval: float,
        thread_name: str,
        caplog: pytest.LogCaptureFixture,
    ):
        test_path = Path("yet_another_file.txt")
        task_done_error = RuntimeError("Some other unexpected task_done error")
        mock_source_queue.task_done.side_effect = task_done_error
        items_returned_count = 0

        def mock_get_side_effect(block, timeout):
            assert timeout == test_poll_interval
            nonlocal items_returned_count
            if items_returned_count == 0:
                items_returned_count += 1
                return test_path
            else:
                real_stop_event.set()
                raise Empty

        mock_source_queue.get.side_effect = mock_get_side_effect

        with caplog.at_level(logging.WARNING, logger=mover_thread_logger.name):
            file_move_thread.start()
            file_move_thread.join(timeout=test_poll_interval * 100)
        assert not file_move_thread.is_alive(), "Thread did not terminate"

        assert find_log_record(
            caplog,
            logging.WARNING,
            [
                f"{thread_name}: task_done() error for {test_path}",
                str(task_done_error),
            ],
        ), f"Log not found. Logs: {caplog.text}"
        mock_process_single.assert_called_once_with(test_path)
        mock_source_queue.task_done.assert_called_once()

        # Cast the sleep_func back to MagicMock so mypy knows assert_not_called exists
        sleep_fn = cast(MagicMock, file_move_thread.sleep_func)
        sleep_fn.assert_not_called()

    def test_stop_method_sets_event_and_logs(
        self,
        file_move_thread: FileMoveThread,  # Thread not started by fixture
        real_stop_event: threading.Event,
        thread_name: str,
        caplog: pytest.LogCaptureFixture,
    ):
        assert not real_stop_event.is_set(), "Stop event should initially be False."
        with caplog.at_level(logging.INFO, logger=mover_thread_logger.name):
            file_move_thread.stop()  # Call stop on the non-started thread

        assert real_stop_event.is_set(), "Stop event should be set after stop() call."
        assert find_log_record(
            caplog, logging.INFO, [f"{thread_name} stop requested"]
        ), f"Log not found. Logs: {caplog.text}"

    def test_stop_method_idempotent(
        self,
        file_move_thread: FileMoveThread,  # Thread not started
        real_stop_event: threading.Event,
        thread_name: str,
        caplog: pytest.LogCaptureFixture,
    ):
        real_stop_event.set()  # Pre-set the event
        with caplog.at_level(logging.DEBUG, logger=mover_thread_logger.name):
            file_move_thread.stop()

        assert real_stop_event.is_set()
        assert find_log_record(
            caplog, logging.DEBUG, [f"{thread_name} stop already requested"]
        ), f"Log not found. Logs: {caplog.text}"

    def test_thread_stops_when_event_set_externally(
        self,
        file_move_thread: FileMoveThread,
        mock_source_queue: MagicMock,
        mock_process_single: MagicMock,
        real_stop_event: threading.Event,
        test_poll_interval: float,
        mock_sleep: MagicMock,  # To assert it's not called for Empty
    ):
        mock_source_queue.get.side_effect = (
            Empty  # Ensure queue.get keeps raising Empty
        )

        file_move_thread.start()
        # Give the thread a moment to enter the loop and call queue.get
        # A short sleep in the test might be needed if timing is critical,
        # but join with timeout is generally preferred for waiting.
        # However, we want to check is_alive *before* setting the event.
        time.sleep(test_poll_interval * 5)  # Allow a few poll cycles

        assert not real_stop_event.is_set(), (
            "Stop event should not be set yet by internal logic."
        )
        assert file_move_thread.is_alive(), "Thread should be alive and polling."

        real_stop_event.set()  # Set the event externally

        file_move_thread.join(timeout=test_poll_interval * 50)

        assert not file_move_thread.is_alive(), "Thread should have terminated."
        mock_process_single.assert_not_called()
        mock_sleep.assert_not_called()  # Importantly, sleep is not called for Empty
