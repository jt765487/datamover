import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch, call
import logging

from datamover.mover.thread_factory import create_file_move_thread
from datamover.mover.mover_thread import FileMoveThread
from datamover.file_functions.fs_mock import FS  # For spec
from datamover.protocols import SafeFileMover, SleepCallable  # For spec

from tests.test_utils.logging_helpers import find_log_record

# --- Define constants for module paths and names ---
FACTORY_MODULE_PATH = "datamover.mover.thread_factory"
PROCESS_SINGLE_LOGGER_NAME = FACTORY_MODULE_PATH
FILE_MOVE_THREAD_CLASS_PATH = f"{FACTORY_MODULE_PATH}.FileMoveThread"
RESOLVE_DIR_FUNC_PATH = f"{FACTORY_MODULE_PATH}.resolve_and_validate_directory"
DEFAULT_MOVER_FUNC_PATH = f"{FACTORY_MODULE_PATH}.move_file_safely_impl"
DEFAULT_SLEEP_FUNC_PATH = (
    f"{FACTORY_MODULE_PATH}.time.sleep"  # Path to time.sleep as used in factory
)


class TestCreateFileMoveThread(unittest.TestCase):
    def setUp(self):
        # Define explicit values that were previously in mock_config
        self.test_source_dir_path = Path("raw/source_for_test")
        self.test_worker_dir_path = Path("raw/destination_for_test")
        self.test_poll_interval = 0.05  # Example poll interval

        self.source_queue = MagicMock(spec=Queue)
        self.stop_event = threading.Event()
        self.mock_fs = MagicMock(spec=FS)
        self.mock_sleep_func = MagicMock(spec=SleepCallable)

        self.resolved_src_dir = Path("/resolved/source")
        self.resolved_dst_dir_name = "destination_folder_resolved"
        self.mock_resolved_dst_dir = MagicMock(spec=Path)
        self.mock_resolved_dst_dir.name = self.resolved_dst_dir_name
        # Mocking how Path objects might be used if needed, e.g. self.mock_resolved_dst_dir / "filename"
        self.mock_resolved_dst_dir.__truediv__ = lambda self_mock, other_name: Path(
            f"/resolved_mock_dest/{other_name}"  # Make it a bit more path-like
        )

        self.patcher_filemovethread = patch(
            FILE_MOVE_THREAD_CLASS_PATH,
            spec=FileMoveThread,  # spec ensures mock matches class
        )
        self.MockFileMoveThread_constructor = self.patcher_filemovethread.start()

        self.patcher_resolve_dir = patch(RESOLVE_DIR_FUNC_PATH)
        self.mock_resolve_and_validate_directory = self.patcher_resolve_dir.start()

        self.mock_resolve_and_validate_directory.side_effect = [
            self.resolved_src_dir,
            self.mock_resolved_dst_dir,
        ]

    def tearDown(self):
        self.patcher_filemovethread.stop()
        self.patcher_resolve_dir.stop()
        self.stop_event.clear()

    def test_create_thread_successful_construction(self):
        mock_created_thread_instance = self.MockFileMoveThread_constructor.return_value
        test_file_mover_func = MagicMock(spec=SafeFileMover)

        thread = create_file_move_thread(
            source_dir_path=self.test_source_dir_path,  # New arg
            worker_dir_path=self.test_worker_dir_path,  # New arg
            poll_interval_seconds=self.test_poll_interval,  # New arg
            source_queue=self.source_queue,
            stop_event=self.stop_event,
            fs=self.mock_fs,
            file_mover_func=test_file_mover_func,
            sleep_func=self.mock_sleep_func,
        )

        self.assertEqual(thread, mock_created_thread_instance)
        self.mock_resolve_and_validate_directory.assert_has_calls(
            [
                call(
                    raw_path=self.test_source_dir_path,  # Updated
                    fs=self.mock_fs,
                    dir_label="source for FileMover",  # Match new label from factory
                ),
                call(
                    raw_path=self.test_worker_dir_path,  # Updated
                    fs=self.mock_fs,
                    dir_label="destination for FileMover (worker)",  # Match new label
                ),
            ],
            any_order=False,
        )
        self.assertEqual(self.mock_resolve_and_validate_directory.call_count, 2)

        expected_thread_name = f"FileMover-{self.resolved_dst_dir_name}"
        self.MockFileMoveThread_constructor.assert_called_once()
        _args, constructor_kwargs = self.MockFileMoveThread_constructor.call_args

        self.assertEqual(constructor_kwargs.get("source_queue"), self.source_queue)
        self.assertTrue(callable(constructor_kwargs.get("process_single")))
        self.assertEqual(constructor_kwargs.get("stop_event"), self.stop_event)
        self.assertEqual(constructor_kwargs.get("sleep_func"), self.mock_sleep_func)
        self.assertEqual(constructor_kwargs.get("name"), expected_thread_name)
        self.assertEqual(
            constructor_kwargs.get("poll_interval"), self.test_poll_interval
        )  # New assertion

    def test_create_thread_uses_default_file_mover_and_sleep(self):
        with (
            patch(DEFAULT_MOVER_FUNC_PATH) as mock_default_mover,
            patch(
                DEFAULT_SLEEP_FUNC_PATH
            ) as mock_default_sleep,  # This patches time.sleep
        ):
            create_file_move_thread(
                source_dir_path=self.test_source_dir_path,  # New arg
                worker_dir_path=self.test_worker_dir_path,  # New arg
                poll_interval_seconds=self.test_poll_interval,  # New arg
                source_queue=self.source_queue,
                stop_event=self.stop_event,
                fs=self.mock_fs,
                # file_mover_func and sleep_func are omitted to test defaults
            )

            self.MockFileMoveThread_constructor.assert_called_once()
            _args, constructor_kwargs = self.MockFileMoveThread_constructor.call_args

            self.assertEqual(constructor_kwargs.get("sleep_func"), mock_default_sleep)
            self.assertEqual(
                constructor_kwargs.get("poll_interval"), self.test_poll_interval
            )  # New assertion

            process_single_func = constructor_kwargs.get("process_single")
            self.assertTrue(callable(process_single_func))

            test_path_to_move = Path("some_file_to_process.txt")
            process_single_func(test_path_to_move)

            mock_default_mover.assert_called_once_with(
                source_path_raw=test_path_to_move,
                expected_source_dir=self.resolved_src_dir,
                destination_dir=self.mock_resolved_dst_dir,
                fs=self.mock_fs,
            )

    def _get_process_single_func_from_factory(
        self, file_mover_to_use: SafeFileMover
    ) -> Callable[[Path], None]:
        self.MockFileMoveThread_constructor.reset_mock()
        self.mock_resolve_and_validate_directory.reset_mock()
        self.mock_resolve_and_validate_directory.side_effect = [
            self.resolved_src_dir,
            self.mock_resolved_dst_dir,
        ]

        create_file_move_thread(
            source_dir_path=self.test_source_dir_path,  # New arg
            worker_dir_path=self.test_worker_dir_path,  # New arg
            poll_interval_seconds=self.test_poll_interval,  # New arg
            source_queue=self.source_queue,
            stop_event=self.stop_event,
            fs=self.mock_fs,
            file_mover_func=file_mover_to_use,
            sleep_func=self.mock_sleep_func,
        )
        self.MockFileMoveThread_constructor.assert_called_once()
        _args, kwargs = self.MockFileMoveThread_constructor.call_args
        process_single_func = kwargs.get("process_single")
        self.assertTrue(callable(process_single_func))
        return process_single_func

    def test_process_single_item_success_logging(self):
        test_path_to_move = Path("source_file.txt")
        expected_final_dest_path_obj = (
            self.mock_resolved_dst_dir
            / test_path_to_move.name  # Using mocked __truediv__
        )

        current_test_mover_mock = MagicMock(
            spec=SafeFileMover, return_value=expected_final_dest_path_obj
        )
        process_single = self._get_process_single_func_from_factory(
            file_mover_to_use=current_test_mover_mock
        )

        thread_name_for_log = f"FileMover-{self.resolved_dst_dir_name}"

        with self.assertLogs(logger=PROCESS_SINGLE_LOGGER_NAME, level="DEBUG") as cm:
            process_single(test_path_to_move)

        current_test_mover_mock.assert_called_once_with(
            source_path_raw=test_path_to_move,
            expected_source_dir=self.resolved_src_dir,
            destination_dir=self.mock_resolved_dst_dir,
            fs=self.mock_fs,
        )
        log_entry = find_log_record(
            cm,
            logging.DEBUG,
            [
                thread_name_for_log,
                "Successfully processed and moved",
                test_path_to_move.name,
                str(expected_final_dest_path_obj),
            ],
        )
        self.assertIsNotNone(log_entry, "Success log message not found or incorrect.")

    def test_process_single_item_failure_mover_returns_none_logging(self):
        test_path_to_move = Path("unmovable_file.txt")
        current_test_mover_mock = MagicMock(spec=SafeFileMover, return_value=None)
        process_single = self._get_process_single_func_from_factory(
            file_mover_to_use=current_test_mover_mock
        )
        thread_name_for_log = f"FileMover-{self.resolved_dst_dir_name}"
        with self.assertLogs(logger=PROCESS_SINGLE_LOGGER_NAME, level="WARNING") as cm:
            process_single(test_path_to_move)

        current_test_mover_mock.assert_called_once_with(
            source_path_raw=test_path_to_move,
            expected_source_dir=self.resolved_src_dir,
            destination_dir=self.mock_resolved_dst_dir,
            fs=self.mock_fs,
        )
        log_entry = find_log_record(
            cm,
            logging.WARNING,
            [
                thread_name_for_log,
                f"Failed to process '{test_path_to_move}'",
                "See previous logs",
            ],
        )
        self.assertIsNotNone(
            log_entry, "Warning log for mover failure not found or incorrect."
        )

    def test_process_single_item_unexpected_exception_in_mover_logging(self):
        test_path_to_move = Path("exploding_file.txt")
        error_message = "Kaboom!"
        mock_exception = RuntimeError(error_message)
        current_test_mover_mock = MagicMock(
            spec=SafeFileMover, side_effect=mock_exception
        )
        process_single = self._get_process_single_func_from_factory(
            file_mover_to_use=current_test_mover_mock
        )
        thread_name_for_log = f"FileMover-{self.resolved_dst_dir_name}"
        with self.assertLogs(logger=PROCESS_SINGLE_LOGGER_NAME, level="ERROR") as cm:
            process_single(test_path_to_move)

        current_test_mover_mock.assert_called_once_with(
            source_path_raw=test_path_to_move,
            expected_source_dir=self.resolved_src_dir,
            destination_dir=self.mock_resolved_dst_dir,
            fs=self.mock_fs,
        )
        log_entry = find_log_record(
            cm,
            logging.ERROR,
            [
                thread_name_for_log,
                f"Unexpected critical error during file processing for '{test_path_to_move}'",
                error_message,
            ],
        )
        self.assertIsNotNone(
            log_entry,
            "Error log for unexpected mover exception not found or incorrect.",
        )
        if log_entry:
            self.assertIsNotNone(log_entry.exc_info)
            self.assertIs(log_entry.exc_info[0], RuntimeError)

    def test_resolve_directory_raises_exception_propagates(self):
        self.mock_resolve_and_validate_directory.reset_mock()
        expected_exception = ValueError("Invalid directory path for test")
        self.mock_resolve_and_validate_directory.side_effect = expected_exception
        test_file_mover_func = MagicMock(spec=SafeFileMover)

        with self.assertRaises(ValueError) as context:
            create_file_move_thread(
                source_dir_path=self.test_source_dir_path,  # New arg
                worker_dir_path=self.test_worker_dir_path,  # New arg
                poll_interval_seconds=self.test_poll_interval,  # New arg
                source_queue=self.source_queue,
                stop_event=self.stop_event,
                fs=self.mock_fs,
                file_mover_func=test_file_mover_func,
                sleep_func=self.mock_sleep_func,
            )
        self.assertIs(context.exception, expected_exception)
        self.MockFileMoveThread_constructor.assert_not_called()
