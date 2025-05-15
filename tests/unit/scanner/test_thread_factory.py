import threading
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock

import pytest

from datamover.file_functions.fs_mock import FS
from datamover.protocols import SleepCallable
from datamover.scanner.do_single_cycle import DoSingleCycle
from datamover.scanner.scan_thread import ScanThread
from datamover.scanner.thread_factory import create_scan_thread

MODULE_PATH = "datamover.scanner.thread_factory"

# Constants for test values
RAW_SCAN_DIR_PATH = Path("/raw/source_for_scanner_factory")
VALIDATED_SCAN_DIR_PATH = Path("/resolved/source_for_scanner_factory")

TEST_SCAN_INTERVAL = 10.0
TEST_LOST_TIMEOUT = 60.0
TEST_STUCK_TIMEOUT = 120.0
TEST_FILE_EXTENSION_NO_DOT = "pcapng"


@pytest.fixture
def scanner_factory_params() -> dict:
    """Provides a dictionary of representative, validated, and correctly formatted
    parameters for create_scan_thread."""
    return {
        "scan_directory_path": RAW_SCAN_DIR_PATH,
        "file_extension_to_scan": TEST_FILE_EXTENSION_NO_DOT,
        "scan_interval_seconds": TEST_SCAN_INTERVAL,
        "lost_timeout_seconds": TEST_LOST_TIMEOUT,
        "stuck_active_file_timeout_seconds": TEST_STUCK_TIMEOUT,
    }


@pytest.fixture
def mock_lost_file_queue() -> MagicMock:
    return MagicMock(spec=Queue)


@pytest.fixture
def mock_stop_event() -> MagicMock:
    return MagicMock(spec=threading.Event)


@pytest.fixture
def mock_fs_instance() -> MagicMock:
    return MagicMock(spec=FS)


@pytest.fixture
def mock_time_func() -> MagicMock:
    return MagicMock(return_value=1700000000.0)


@pytest.fixture
def mock_monotonic_func() -> MagicMock:
    return MagicMock(return_value=5000.0)


@pytest.fixture
def mock_custom_sleep_func() -> MagicMock:
    return MagicMock(spec=SleepCallable)


@pytest.fixture
def patch_resolve_validate_directory(mocker) -> MagicMock:
    return mocker.patch(
        f"{MODULE_PATH}.resolve_and_validate_directory",
        return_value=VALIDATED_SCAN_DIR_PATH,
        autospec=True,
    )


@pytest.fixture
def patch_do_single_cycle_constructor(mocker) -> MagicMock:
    mock_processor_instance = MagicMock(spec=DoSingleCycle)
    mock_processor_instance.directory_to_scan = VALIDATED_SCAN_DIR_PATH
    mock_processor_instance.lost_queue_name = (
        f"LostFileQ-{VALIDATED_SCAN_DIR_PATH.name}"
    )
    return mocker.patch(
        f"{MODULE_PATH}.DoSingleCycle",
        return_value=mock_processor_instance,
        autospec=True,
    )


@pytest.fixture
def patch_scan_thread_constructor(mocker) -> MagicMock:
    mock_thread_instance = MagicMock(spec=ScanThread)
    return mocker.patch(
        f"{MODULE_PATH}.ScanThread",
        return_value=mock_thread_instance,
        autospec=True,
    )


@pytest.fixture
def patch_default_time_sleep(mocker) -> MagicMock:
    # This patches 'time.sleep' specifically in the context of the factory module
    return mocker.patch(f"{MODULE_PATH}.time.sleep", autospec=True)


class TestCreateScanThread:
    @pytest.mark.parametrize(
        "use_custom_sleep", [True, False], ids=["custom_sleep", "default_sleep"]
    )
    def test_successful_creation(
        self,
        scanner_factory_params: dict,
        mock_lost_file_queue: MagicMock,
        mock_stop_event: MagicMock,
        mock_fs_instance: MagicMock,
        mock_time_func: MagicMock,
        mock_monotonic_func: MagicMock,
        mock_custom_sleep_func: MagicMock,
        patch_resolve_validate_directory: MagicMock,
        patch_do_single_cycle_constructor: MagicMock,
        patch_scan_thread_constructor: MagicMock,
        patch_default_time_sleep: MagicMock,
        use_custom_sleep: bool,
    ):
        sleep_func_to_pass = mock_custom_sleep_func if use_custom_sleep else None
        expected_sleep_for_thread = (
            mock_custom_sleep_func if use_custom_sleep else patch_default_time_sleep
        )

        # --- Act ---
        returned_thread = create_scan_thread(
            scan_directory_path=scanner_factory_params["scan_directory_path"],
            file_extension_to_scan=scanner_factory_params[
                "file_extension_to_scan"
            ],  # Directly use
            scan_interval_seconds=scanner_factory_params["scan_interval_seconds"],
            lost_timeout_seconds=scanner_factory_params["lost_timeout_seconds"],
            stuck_active_file_timeout_seconds=scanner_factory_params[
                "stuck_active_file_timeout_seconds"
            ],
            lost_file_queue=mock_lost_file_queue,
            stop_event=mock_stop_event,
            fs=mock_fs_instance,
            time_func=mock_time_func,
            monotonic_func=mock_monotonic_func,
            sleep_func=sleep_func_to_pass,
        )

        # --- Assert Directory Validation ---
        patch_resolve_validate_directory.assert_called_once_with(
            raw_path=scanner_factory_params["scan_directory_path"],
            fs=mock_fs_instance,
            dir_label="scan source directory",
        )

        # --- Assert DoSingleCycle Processor Creation ---
        patch_do_single_cycle_constructor.assert_called_once_with(
            validated_directory_to_scan=VALIDATED_SCAN_DIR_PATH,
            # Expects the already normalized extension from scanner_factory_params
            extension_to_scan_no_dot=scanner_factory_params["file_extension_to_scan"],
            lost_timeout=scanner_factory_params["lost_timeout_seconds"],
            stuck_active_file_timeout=scanner_factory_params[
                "stuck_active_file_timeout_seconds"
            ],
            lost_file_queue=mock_lost_file_queue,
            time_func=mock_time_func,
            monotonic_func=mock_monotonic_func,
            fs=mock_fs_instance,
        )
        created_processor_instance = patch_do_single_cycle_constructor.return_value

        # --- Assert ScanThread Creation ---
        expected_thread_name = f"Scanner-{VALIDATED_SCAN_DIR_PATH.name}"
        patch_scan_thread_constructor.assert_called_once_with(
            processor=created_processor_instance,
            stop_event=mock_stop_event,
            scan_interval_seconds=scanner_factory_params["scan_interval_seconds"],
            sleep_func=expected_sleep_for_thread,
            monotonic_func=mock_monotonic_func,
            name=expected_thread_name,
        )
        # The factory itself doesn't call the default sleep, it just passes the function reference.
        patch_default_time_sleep.assert_not_called()
        assert returned_thread is patch_scan_thread_constructor.return_value

    @pytest.mark.parametrize(
        "exception_type, error_message",
        [
            (FileNotFoundError, "Mock directory not found"),
            (NotADirectoryError, "Mock path is not a directory"),
            (ValueError, "Mock invalid configuration value for dir"),
            (PermissionError, "Mock permission denied for dir"),
        ],
        ids=[
            "dir_not_found",
            "path_not_dir",
            "dir_value_error",
            "dir_permission_error",
        ],
    )
    def test_directory_validation_failure_propagates(
        self,
        exception_type: type[Exception],
        error_message: str,
        scanner_factory_params: dict,
        mock_lost_file_queue: MagicMock,
        mock_stop_event: MagicMock,
        mock_fs_instance: MagicMock,
        patch_resolve_validate_directory: MagicMock,
        patch_do_single_cycle_constructor: MagicMock,
        patch_scan_thread_constructor: MagicMock,
    ):
        patch_resolve_validate_directory.side_effect = exception_type(error_message)

        with pytest.raises(exception_type, match=error_message):
            create_scan_thread(
                scan_directory_path=scanner_factory_params["scan_directory_path"],
                file_extension_to_scan=scanner_factory_params["file_extension_to_scan"],
                scan_interval_seconds=scanner_factory_params["scan_interval_seconds"],
                lost_timeout_seconds=scanner_factory_params["lost_timeout_seconds"],
                stuck_active_file_timeout_seconds=scanner_factory_params[
                    "stuck_active_file_timeout_seconds"
                ],
                lost_file_queue=mock_lost_file_queue,
                stop_event=mock_stop_event,
                fs=mock_fs_instance,
                time_func=MagicMock(),
                monotonic_func=MagicMock(),
                sleep_func=None,
            )

        patch_resolve_validate_directory.assert_called_once_with(
            raw_path=scanner_factory_params["scan_directory_path"],
            fs=mock_fs_instance,
            dir_label="scan source directory",
        )
        patch_do_single_cycle_constructor.assert_not_called()
        patch_scan_thread_constructor.assert_not_called()
