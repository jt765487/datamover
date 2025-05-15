import logging
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from watchdog.observers.api import BaseObserver

from datamover.file_functions.file_exceptions import ScanDirectoryError
from datamover.protocols import FileScanner
from datamover.queues.queue_functions import QueuePutError
from datamover.tailer.data_class import TailerQueueEvent, InitialFoundEvent
from datamover.tailer.tail_consumer_thread import TailConsumerThread
from datamover.tailer.thread_factory import (
    create_csv_tailer_thread,
    INITIAL_SCAN_QUEUE_NAME,
)
from tests.test_utils.logging_helpers import find_log_record

SUT_MODULE_PATH = "datamover.tailer.thread_factory"

TEST_CSV_EXTENSION_NO_DOT = "csv"
TEST_POLE_INTERVAL = 0.02


@pytest.fixture
def event_queue() -> queue.Queue[TailerQueueEvent]:
    return queue.Queue()


@pytest.fixture
def move_queue() -> queue.Queue[Path]:
    return queue.Queue()


@pytest.fixture
def mock_file_scanner() -> MagicMock:
    return MagicMock(spec=FileScanner)


class MockGatheredEntryData:
    def __init__(self, path: Path):
        self.path: Path = path
        self.name: str = path.name

    def __repr__(self):
        return f"MockGatheredEntryData(path='{self.path}')"

    def __eq__(self, other):
        if isinstance(other, MockGatheredEntryData):
            return self.path == other.path
        return NotImplemented


@patch(f"{SUT_MODULE_PATH}.TailConsumerThread", autospec=True)
@patch(f"{SUT_MODULE_PATH}.TailProcessor", autospec=True)
@patch(f"{SUT_MODULE_PATH}.MappingEventHandler", autospec=True)
@patch(f"{SUT_MODULE_PATH}.Observer", autospec=True)
@patch(f"{SUT_MODULE_PATH}.safe_put", autospec=True)
class TestCreateCsvTailerThread:
    def test_successful_setup_with_initial_files(
        self,
        mock_safe_put_arg: MagicMock,
        MockObserver_arg: MagicMock,
        MockMappingEventHandler_arg: MagicMock,
        MockTailProcessor_arg: MagicMock,
        MockTailConsumerThread_arg: MagicMock,  # This is the mock for the TailConsumerThread CLASS
        mock_config: MagicMock,
        event_queue: queue.Queue,
        move_queue: queue.Queue,
        mock_stop_event: MagicMock,
        mock_fs: MagicMock,
        mock_file_scanner: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        csv_dir_to_watch = mock_config.csv_dir
        csv_dir_to_watch.mkdir(parents=True, exist_ok=True)

        scanned_file_1_path = csv_dir_to_watch / f"file1.{TEST_CSV_EXTENSION_NO_DOT}"
        scanned_file_2_path = csv_dir_to_watch / f"file2.{TEST_CSV_EXTENSION_NO_DOT}"

        mock_fs.resolve.side_effect = lambda p: Path(p)

        mock_file_scanner.return_value = [
            MockGatheredEntryData(path=scanned_file_1_path),
            MockGatheredEntryData(path=scanned_file_2_path),
        ]

        # Get the mock instances that will be returned by the patched constructors
        mock_handler_instance = MockMappingEventHandler_arg.return_value
        mock_observer_instance = MockObserver_arg.return_value
        mock_processor_instance = MockTailProcessor_arg.return_value
        mock_tail_thread_instance = (
            MockTailConsumerThread_arg.return_value
        )  # This is the mock INSTANCE

        expected_consumer_name = f"TailConsumer-{csv_dir_to_watch.name}"
        mock_tail_thread_instance.name = (
            expected_consumer_name  # Set the name on the mock instance
        )

        # --- Act ---
        observer, tail_thread = create_csv_tailer_thread(
            csv_directory_to_watch=csv_dir_to_watch,
            csv_file_extension_no_dot=TEST_CSV_EXTENSION_NO_DOT,
            event_queue=event_queue,
            move_queue=move_queue,
            stop_event=mock_stop_event,
            fs=mock_fs,
            file_scanner=mock_file_scanner,
            poll_interval=TEST_POLE_INTERVAL,
        )

        # --- Assertions ---
        mock_file_scanner.assert_called_once_with(
            directory=csv_dir_to_watch,
            fs=mock_fs,
            extension_no_dot=TEST_CSV_EXTENSION_NO_DOT,
        )
        mock_fs.resolve.assert_has_calls(
            [call(scanned_file_1_path), call(scanned_file_2_path)], any_order=True
        )

        expected_event1 = InitialFoundEvent(path=str(scanned_file_1_path))
        expected_event2 = InitialFoundEvent(path=str(scanned_file_2_path))
        mock_safe_put_arg.assert_has_calls(
            [
                call(
                    item=expected_event1,
                    output_queue=event_queue,
                    queue_name=INITIAL_SCAN_QUEUE_NAME,
                ),
                call(
                    item=expected_event2,
                    output_queue=event_queue,
                    queue_name=INITIAL_SCAN_QUEUE_NAME,
                ),
            ],
            any_order=True,
        )
        assert mock_safe_put_arg.call_count == 2

        MockMappingEventHandler_arg.assert_called_once_with(
            file_map={str(scanned_file_1_path), str(scanned_file_2_path)},
            event_queue=event_queue,
            watched_directory=csv_dir_to_watch,
            fs=mock_fs,
            file_extension=TEST_CSV_EXTENSION_NO_DOT,
        )

        MockObserver_arg.assert_called_once_with()
        mock_observer_instance.schedule.assert_called_once_with(
            mock_handler_instance, str(csv_dir_to_watch), recursive=False
        )
        assert isinstance(observer, BaseObserver)
        assert observer is mock_observer_instance

        expected_processor_q_name = f"MoveQueueFrom-{csv_dir_to_watch.name}"
        MockTailProcessor_arg.assert_called_once_with(
            fs=mock_fs,
            move_queue=move_queue,
            move_queue_name=expected_processor_q_name,
        )

        # The constructor mock (MockTailConsumerThread_arg) is checked here
        MockTailConsumerThread_arg.assert_called_once_with(
            event_queue=event_queue,
            stop_event=mock_stop_event,
            processor=mock_processor_instance,
            name=expected_consumer_name,  # SUT passes this name to constructor
            poll_interval=TEST_POLE_INTERVAL,
        )
        assert isinstance(
            tail_thread, TailConsumerThread
        )  # tail_thread is the mock_tail_thread_instance
        assert tail_thread is mock_tail_thread_instance

        # --- Log Assertions ---
        assert (
            find_log_record(
                caplog,
                logging.INFO,
                ["Configuring CSV tailer for directory", str(csv_dir_to_watch)],
            )
            is not None
        )
        assert (
            find_log_record(
                caplog, logging.INFO, ["Initial scan found 2 files matching"]
            )
            is not None
        )
        assert (
            find_log_record(
                caplog, logging.INFO, ["Finished enqueuing 2 initial file events"]
            )
            is not None
        )
        assert (
            find_log_record(
                caplog,
                logging.INFO,
                ["Watchdog observer scheduled for directory", str(csv_dir_to_watch)],
            )
            is not None
        )

        # Now this log assertion should work because mock_tail_thread_instance.name is set
        assert (
            find_log_record(
                caplog,
                logging.INFO,
                [
                    f"TailConsumerThread '{expected_consumer_name}' initialized to process events for",
                    str(csv_dir_to_watch),
                ],
            )
            is not None
        ), "TailConsumerThread initialization log not found or incorrect."

    def test_successful_setup_no_initial_files(
        self,
        mock_safe_put_arg: MagicMock,
        MockObserver_arg: MagicMock,
        MockMappingEventHandler_arg: MagicMock,
        MockTailProcessor_arg: MagicMock,
        MockTailConsumerThread_arg: MagicMock,
        mock_config: MagicMock,
        event_queue: queue.Queue,
        move_queue: queue.Queue,
        mock_stop_event: MagicMock,
        mock_fs: MagicMock,
        mock_file_scanner: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        csv_dir_to_watch = mock_config.csv_dir
        csv_dir_to_watch.mkdir(parents=True, exist_ok=True)
        mock_file_scanner.return_value = []

        mock_observer_instance = MockObserver_arg.return_value

        observer, tail_thread = create_csv_tailer_thread(
            csv_directory_to_watch=csv_dir_to_watch,
            csv_file_extension_no_dot=TEST_CSV_EXTENSION_NO_DOT,
            event_queue=event_queue,
            move_queue=move_queue,
            stop_event=mock_stop_event,
            fs=mock_fs,
            file_scanner=mock_file_scanner,
            poll_interval=TEST_POLE_INTERVAL,
        )

        mock_file_scanner.assert_called_once()
        mock_fs.resolve.assert_not_called()
        mock_safe_put_arg.assert_not_called()

        MockMappingEventHandler_arg.assert_called_once_with(
            file_map=set(),
            event_queue=event_queue,
            watched_directory=csv_dir_to_watch,
            fs=mock_fs,
            file_extension=TEST_CSV_EXTENSION_NO_DOT,
        )
        mock_observer_instance.schedule.assert_called_once()

        assert (
            find_log_record(
                caplog, logging.INFO, ["Initial scan found 0 files matching"]
            )
            is not None
        )
        assert (
            find_log_record(
                caplog, logging.INFO, ["Finished enqueuing 0 initial file events"]
            )
            is not None
        )
        assert observer is mock_observer_instance
        assert tail_thread is MockTailConsumerThread_arg.return_value

    def test_initial_scan_raises_scan_directory_error(
        self,
        mock_safe_put_arg: MagicMock,
        MockObserver_arg: MagicMock,
        MockMappingEventHandler_arg: MagicMock,
        MockTailProcessor_arg: MagicMock,
        MockTailConsumerThread_arg: MagicMock,
        mock_config: MagicMock,
        event_queue: queue.Queue,
        move_queue: queue.Queue,
        mock_stop_event: MagicMock,
        mock_fs: MagicMock,
        mock_file_scanner: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.ERROR)
        csv_dir_to_watch = mock_config.csv_dir
        csv_dir_to_watch.mkdir(parents=True, exist_ok=True)

        scan_error = ScanDirectoryError(
            message="Test scan failed",
            directory=csv_dir_to_watch,
            original_exception=RuntimeError("Simulated scanner problem"),
        )
        mock_file_scanner.side_effect = scan_error

        with pytest.raises(ScanDirectoryError) as excinfo:
            create_csv_tailer_thread(
                csv_directory_to_watch=csv_dir_to_watch,
                csv_file_extension_no_dot=TEST_CSV_EXTENSION_NO_DOT,
                event_queue=event_queue,
                move_queue=move_queue,
                stop_event=mock_stop_event,
                fs=mock_fs,
                file_scanner=mock_file_scanner,
                poll_interval=TEST_POLE_INTERVAL,
            )
        assert excinfo.value is scan_error
        assert (
            find_log_record(
                caplog,
                logging.ERROR,
                ["Critical error during initial scan", str(csv_dir_to_watch)],
            )
            is not None
        )

        MockObserver_arg.return_value.schedule.assert_not_called()
        mock_safe_put_arg.assert_not_called()

    def test_fs_resolve_fails_for_one_file_during_scan(
        self,
        mock_safe_put_arg: MagicMock,
        MockObserver_arg: MagicMock,
        MockMappingEventHandler_arg: MagicMock,
        MockTailProcessor_arg: MagicMock,
        MockTailConsumerThread_arg: MagicMock,
        mock_config: MagicMock,
        event_queue: queue.Queue,
        move_queue: queue.Queue,
        mock_stop_event: MagicMock,
        mock_fs: MagicMock,
        mock_file_scanner: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING)
        csv_dir_to_watch = mock_config.csv_dir
        csv_dir_to_watch.mkdir(parents=True, exist_ok=True)

        file1_path = csv_dir_to_watch / "file1.csv"
        file2_unresolvable_path = csv_dir_to_watch / "file2_unresolvable.csv"

        mock_file_scanner.return_value = [
            MockGatheredEntryData(path=file1_path),
            MockGatheredEntryData(path=file2_unresolvable_path),
        ]
        resolve_error = FileNotFoundError(f"Test FNF for: {file2_unresolvable_path}")

        def resolve_side_effect(path_arg):
            if path_arg == file1_path:
                return file1_path
            if path_arg == file2_unresolvable_path:
                raise resolve_error
            pytest.fail(f"Unexpected path to fs.resolve: {path_arg}")

        mock_fs.resolve.side_effect = resolve_side_effect

        create_csv_tailer_thread(
            csv_directory_to_watch=csv_dir_to_watch,
            csv_file_extension_no_dot=TEST_CSV_EXTENSION_NO_DOT,
            event_queue=event_queue,
            move_queue=move_queue,
            stop_event=mock_stop_event,
            fs=mock_fs,
            file_scanner=mock_file_scanner,
            poll_interval=TEST_POLE_INTERVAL,
        )

        mock_safe_put_arg.assert_called_once_with(
            item=InitialFoundEvent(path=str(file1_path)),
            output_queue=event_queue,
            queue_name=INITIAL_SCAN_QUEUE_NAME,
        )
        assert (
            find_log_record(
                caplog,
                logging.WARNING,
                [
                    "Could not resolve path",
                    str(file2_unresolvable_path),
                    str(resolve_error),
                ],
            )
            is not None
        )

        MockMappingEventHandler_arg.assert_called_once()
        _args_handler, kwargs_handler = MockMappingEventHandler_arg.call_args
        assert str(file1_path) in kwargs_handler.get("file_map", set())
        assert str(file2_unresolvable_path) not in kwargs_handler.get("file_map", set())
        assert len(kwargs_handler.get("file_map", set())) == 1

    def test_safe_put_fails_during_initial_scan_enqueue(
        self,
        mock_safe_put_arg: MagicMock,
        MockObserver_arg: MagicMock,
        MockMappingEventHandler_arg: MagicMock,
        MockTailProcessor_arg: MagicMock,
        MockTailConsumerThread_arg: MagicMock,
        mock_config: MagicMock,
        event_queue: queue.Queue,
        move_queue: queue.Queue,
        mock_stop_event: MagicMock,
        mock_fs: MagicMock,
        mock_file_scanner: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.CRITICAL)
        csv_dir_to_watch = mock_config.csv_dir
        csv_dir_to_watch.mkdir(parents=True, exist_ok=True)

        file1_path = csv_dir_to_watch / "file1.csv"
        mock_file_scanner.return_value = [MockGatheredEntryData(path=file1_path)]
        mock_fs.resolve.return_value = file1_path

        put_error = QueuePutError("Test queue full")
        mock_safe_put_arg.side_effect = put_error

        with pytest.raises(QueuePutError) as excinfo:
            create_csv_tailer_thread(
                csv_directory_to_watch=csv_dir_to_watch,
                csv_file_extension_no_dot=TEST_CSV_EXTENSION_NO_DOT,
                event_queue=event_queue,
                move_queue=move_queue,
                stop_event=mock_stop_event,
                fs=mock_fs,
                file_scanner=mock_file_scanner,
                poll_interval=TEST_POLE_INTERVAL,
            )
        assert excinfo.value is put_error
        expected_event = InitialFoundEvent(path=str(file1_path))
        assert (
            find_log_record(
                caplog,
                logging.CRITICAL,
                [
                    "Failed to enqueue initial file event",
                    str(expected_event),
                    INITIAL_SCAN_QUEUE_NAME,
                    str(put_error),
                ],
            )
            is not None
        )
        MockObserver_arg.return_value.schedule.assert_not_called()

    def test_mapping_event_handler_init_fails(
        self,
        mock_safe_put_arg: MagicMock,
        MockObserver_arg: MagicMock,
        MockMappingEventHandler_arg: MagicMock,
        MockTailProcessor_arg: MagicMock,
        MockTailConsumerThread_arg: MagicMock,
        mock_config: MagicMock,
        event_queue: queue.Queue,
        move_queue: queue.Queue,
        mock_stop_event: MagicMock,
        mock_fs: MagicMock,
        mock_file_scanner: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.ERROR)
        csv_dir_to_watch = mock_config.csv_dir
        csv_dir_to_watch.mkdir(parents=True, exist_ok=True)
        mock_file_scanner.return_value = []

        init_error = ValueError("Test MappingEventHandler init failure")
        MockMappingEventHandler_arg.side_effect = init_error

        with pytest.raises(ValueError) as excinfo:
            create_csv_tailer_thread(
                csv_directory_to_watch=csv_dir_to_watch,
                csv_file_extension_no_dot=TEST_CSV_EXTENSION_NO_DOT,
                event_queue=event_queue,
                move_queue=move_queue,
                stop_event=mock_stop_event,
                fs=mock_fs,
                file_scanner=mock_file_scanner,
                poll_interval=TEST_POLE_INTERVAL,
            )

        # SUT re-raises the original ValueError 'e' from handler init
        assert excinfo.value is init_error
        # The log message is from the factory, the exception is the original one
        assert (
            find_log_record(
                caplog,
                logging.ERROR,
                [
                    "MappingEventHandler setup failed",
                    str(csv_dir_to_watch),
                    str(init_error),
                ],
            )
            is not None
        )
        MockMappingEventHandler_arg.assert_called_once()  # Constructor was called
        MockObserver_arg.return_value.schedule.assert_not_called()

    def test_tail_processor_init_fails(
        self,
        mock_safe_put_arg: MagicMock,
        MockObserver_arg: MagicMock,
        MockMappingEventHandler_arg: MagicMock,
        MockTailProcessor_arg: MagicMock,
        MockTailConsumerThread_arg: MagicMock,
        mock_config: MagicMock,
        event_queue: queue.Queue,
        move_queue: queue.Queue,
        mock_stop_event: MagicMock,
        mock_fs: MagicMock,
        mock_file_scanner: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.ERROR)
        csv_dir_to_watch = mock_config.csv_dir
        csv_dir_to_watch.mkdir(parents=True, exist_ok=True)
        mock_file_scanner.return_value = []

        mock_observer_instance = MockObserver_arg.return_value

        init_error = RuntimeError("Test TailProcessor init failure")
        MockTailProcessor_arg.side_effect = init_error

        with pytest.raises(ValueError) as excinfo:  # SUT wraps and raises ValueError
            create_csv_tailer_thread(
                csv_directory_to_watch=csv_dir_to_watch,
                csv_file_extension_no_dot=TEST_CSV_EXTENSION_NO_DOT,
                event_queue=event_queue,
                move_queue=move_queue,
                stop_event=mock_stop_event,
                fs=mock_fs,
                file_scanner=mock_file_scanner,
                poll_interval=TEST_POLE_INTERVAL,
            )

        assert "TailProcessor initialization failed" == str(
            excinfo.value
        )  # Check message of new ValueError
        assert excinfo.value.__cause__ is init_error  # Check original cause

        MockMappingEventHandler_arg.assert_called_once()
        MockObserver_arg.assert_called_once()
        mock_observer_instance.schedule.assert_called_once()
        MockTailProcessor_arg.assert_called_once()
        assert (
            find_log_record(
                caplog,
                logging.ERROR,
                ["TailProcessor initialization failed", str(init_error)],
            )
            is not None
        )
