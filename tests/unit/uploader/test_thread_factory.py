import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Concrete implementations that the factory might use or for spec in mocks
from datamover.file_functions.fs_mock import FS  # Renamed from RealFS for consistency
from datamover.file_functions.move_file_safely import move_file_safely_impl
from datamover.file_functions.scan_directory_and_filter import (
    scan_directory_and_filter,
)

# HttpClient for spec
from datamover.protocols import HttpClient, FileScanner, SafeFileMover

# Classes instantiated by the factory (will be patched)
from datamover.uploader.send_file_with_retries import RetryableFileSender

# Function under test and its new settings dataclasses
from datamover.uploader.thread_factory import (
    create_uploader_thread,
    UploaderOperationalSettings,  # Import new dataclass
    SenderConnectionConfig,  # Import new dataclass
)
from tests.test_utils.logging_helpers import find_log_record

# DEFAULT_POLL_INTERVAL and DEFAULT_FILE_EXTENSION are no longer used by the factory itself.
# Tests will define their own "default" values to pass in the settings objects.

# Define the module path for patching based on where create_uploader_thread is.
SUT_MODULE_PATH = "datamover.uploader.thread_factory"

# --- Test-specific Constants for default/representative values ---
TEST_WORKER_DIR = Path("/test/worker")
TEST_UPLOADED_DIR = Path("/test/uploaded")
TEST_DEAD_LETTER_DIR = Path("/test/dead_letter")
TEST_FILE_EXTENSION = "pcap"  # Default for tests (no dot)
TEST_POLL_INTERVAL = 1.0  # Default for tests
TEST_HEARTBEAT_INTERVAL = 60.0  # Default for tests

TEST_REMOTE_URL = "http://testhost.com/api"
TEST_REQUEST_TIMEOUT = 30.0
TEST_VERIFY_SSL = True
TEST_INITIAL_BACKOFF = 1.0
TEST_MAX_BACKOFF = 60.0


@pytest.fixture
def default_uploader_op_settings() -> UploaderOperationalSettings:
    return UploaderOperationalSettings(
        worker_dir_path=TEST_WORKER_DIR,
        uploaded_dir_path=TEST_UPLOADED_DIR,
        dead_letter_dir_path=TEST_DEAD_LETTER_DIR,
        file_extension_to_scan=TEST_FILE_EXTENSION,
        poll_interval_seconds=TEST_POLL_INTERVAL,
        heartbeat_interval_seconds=TEST_HEARTBEAT_INTERVAL,
    )


@pytest.fixture
def default_sender_conn_config() -> SenderConnectionConfig:
    return SenderConnectionConfig(
        remote_host_url=TEST_REMOTE_URL,
        request_timeout_seconds=TEST_REQUEST_TIMEOUT,
        verify_ssl=TEST_VERIFY_SSL,
        initial_backoff_seconds=TEST_INITIAL_BACKOFF,
        max_backoff_seconds=TEST_MAX_BACKOFF,
    )


@pytest.fixture
def stop_event() -> threading.Event:
    return threading.Event()


@pytest.fixture
def mock_fs_dependency() -> MagicMock:
    return MagicMock(spec=FS, name="injected_mock_fs_instance")


@pytest.fixture
def mock_http_client_dependency() -> MagicMock:
    return MagicMock(spec=HttpClient, name="injected_mock_http_client_instance")


# Patching the constructors of classes instantiated *within* the factory
# These patches apply to all methods in the class due to class-level decoration
@patch(f"{SUT_MODULE_PATH}.UploaderThread", autospec=True)
@patch(f"{SUT_MODULE_PATH}.RetryableFileSender", autospec=True)
# Patch resolve_and_validate_directory as it's called by the factory
@patch(f"{SUT_MODULE_PATH}.resolve_and_validate_directory", autospec=True)
class TestCreateUploaderThread:
    def test_successful_creation_with_defaults(
        self,
        mock_resolve_validate_directory: MagicMock,  # Patched
        MockRetryableFileSender: MagicMock,
        MockUploaderThread: MagicMock,
        default_uploader_op_settings: UploaderOperationalSettings,  # Fixture
        default_sender_conn_config: SenderConnectionConfig,  # Fixture
        stop_event: threading.Event,
        mock_fs_dependency: MagicMock,
        mock_http_client_dependency: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)

        # Configure mock for resolve_and_validate_directory
        validated_worker_dir_mock = Path("/validated/worker")  # This is the mock return
        mock_resolve_validate_directory.return_value = validated_worker_dir_mock

        mock_sender_instance = MockRetryableFileSender.return_value
        mock_uploader_thread_instance = MockUploaderThread.return_value
        # The thread name is derived from the *validated* worker directory name
        expected_thread_name = f"Uploader-{validated_worker_dir_mock.name}"
        mock_uploader_thread_instance.name = (
            expected_thread_name  # Set for the second log check
        )

        # Act
        returned_thread = create_uploader_thread(
            uploader_op_settings=default_uploader_op_settings,
            sender_conn_config=default_sender_conn_config,
            stop_event=stop_event,
            fs=mock_fs_dependency,
            http_client=mock_http_client_dependency,
            # file_scanner_impl and safe_file_mover_impl use factory defaults
        )

        # Assert resolve_and_validate_directory call
        mock_resolve_validate_directory.assert_called_once_with(
            raw_path=default_uploader_op_settings.worker_dir_path,  # This is Path("/test/worker")
            fs=mock_fs_dependency,
            dir_label="uploader source (worker) directory",
        )

        # Assert RetryableFileSender instantiation
        MockRetryableFileSender.assert_called_once_with(
            remote_url=default_sender_conn_config.remote_host_url,
            request_timeout_seconds=default_sender_conn_config.request_timeout_seconds,
            verify_ssl=default_sender_conn_config.verify_ssl,
            initial_backoff_seconds=default_sender_conn_config.initial_backoff_seconds,
            max_backoff_seconds=default_sender_conn_config.max_backoff_seconds,
            uploaded_destination_dir=default_uploader_op_settings.uploaded_dir_path,
            dead_letter_destination_dir=default_uploader_op_settings.dead_letter_dir_path,
            http_client=mock_http_client_dependency,
            fs=mock_fs_dependency,
            stop_event=stop_event,
            safe_file_mover=move_file_safely_impl,
        )

        # Assert UploaderThread instantiation
        MockUploaderThread.assert_called_once_with(
            thread_name=expected_thread_name,
            validated_work_dir=validated_worker_dir_mock,
            file_extension_no_dot=default_uploader_op_settings.file_extension_to_scan,
            stop_event=stop_event,
            poll_interval=default_uploader_op_settings.poll_interval_seconds,
            heartbeat_interval=default_uploader_op_settings.heartbeat_interval_seconds,
            file_scanner=scan_directory_and_filter,
            file_sender=mock_sender_instance,
            fs=mock_fs_dependency,
        )

        assert returned_thread is mock_uploader_thread_instance

        # Check for the initial creation log from the factory - CORRECTED SUBSTRINGS
        # Actual log: "Creating UploaderThread for worker dir: '/test/worker', sender URL: 'http://testhost.com/api'"
        assert (
            find_log_record(
                caplog,
                logging.INFO,
                [
                    "Creating UploaderThread for worker dir:",  # Matches actual log
                    str(
                        default_uploader_op_settings.worker_dir_path
                    ),  # Should be '/test/worker'
                    ", sender URL:",  # Matches actual log (includes comma)
                    default_sender_conn_config.remote_host_url,  # Should be 'http://testhost.com/api'
                ],
            )
            is not None
        ), (
            f"Initial factory log message not found or incorrect. "
            f"Expected parts: 'Creating UploaderThread for worker dir:', "
            f"'{str(default_uploader_op_settings.worker_dir_path)}', "
            f"', sender URL:', '{default_sender_conn_config.remote_host_url}'"
        )

        # Check for the success log from the factory - CORRECTED SUBSTRINGS
        # Actual log: "Successfully configured UploaderThread: Uploader-worker"
        # where expected_thread_name is "Uploader-worker" (since validated_worker_dir_mock.name is "worker")
        assert (
            find_log_record(
                caplog,
                logging.INFO,
                [
                    "Successfully configured UploaderThread:",  # Substring part 1
                    expected_thread_name,  # Substring part 2 (dynamic)
                ],
            )
            is not None
        ), (
            f"Successful configuration log message not found or incorrect. "
            f"Expected parts: 'Successfully configured UploaderThread:', '{expected_thread_name}'"
        )

    def test_successful_creation_with_custom_implementations(
        self,
        mock_resolve_validate_directory: MagicMock,
        MockRetryableFileSender: MagicMock,
        MockUploaderThread: MagicMock,
        default_uploader_op_settings: UploaderOperationalSettings,
        default_sender_conn_config: SenderConnectionConfig,
        stop_event: threading.Event,
        mock_fs_dependency: MagicMock,
        mock_http_client_dependency: MagicMock,
    ):
        """Tests creation with custom file_scanner and safe_mover implementations."""
        custom_scanner = MagicMock(spec=FileScanner)
        custom_mover = MagicMock(spec=SafeFileMover)

        validated_worker_dir_mock = Path("/validated/custom/worker")
        mock_resolve_validate_directory.return_value = validated_worker_dir_mock

        mock_sender_instance = MockRetryableFileSender.return_value
        mock_uploader_thread_instance = MockUploaderThread.return_value
        expected_thread_name = (
            f"Uploader-{validated_worker_dir_mock.name}"  # Name from validated dir
        )
        mock_uploader_thread_instance.name = expected_thread_name

        # Act
        returned_thread = create_uploader_thread(
            uploader_op_settings=default_uploader_op_settings,  # Can use defaults for settings objects
            sender_conn_config=default_sender_conn_config,
            stop_event=stop_event,
            fs=mock_fs_dependency,
            http_client=mock_http_client_dependency,
            file_scanner_impl=custom_scanner,  # Override
            safe_file_mover_impl=custom_mover,  # Override
        )

        # Assert RetryableFileSender instantiation with custom mover
        MockRetryableFileSender.assert_called_once_with(
            remote_url=default_sender_conn_config.remote_host_url,
            request_timeout_seconds=default_sender_conn_config.request_timeout_seconds,
            verify_ssl=default_sender_conn_config.verify_ssl,
            initial_backoff_seconds=default_sender_conn_config.initial_backoff_seconds,
            max_backoff_seconds=default_sender_conn_config.max_backoff_seconds,
            uploaded_destination_dir=default_uploader_op_settings.uploaded_dir_path,
            dead_letter_destination_dir=default_uploader_op_settings.dead_letter_dir_path,
            http_client=mock_http_client_dependency,
            fs=mock_fs_dependency,
            stop_event=stop_event,
            safe_file_mover=custom_mover,  # Check custom mover
        )

        # Assert UploaderThread instantiation with custom scanner
        MockUploaderThread.assert_called_once_with(
            thread_name=expected_thread_name,
            validated_work_dir=validated_worker_dir_mock,
            file_extension_no_dot=default_uploader_op_settings.file_extension_to_scan,
            stop_event=stop_event,
            poll_interval=default_uploader_op_settings.poll_interval_seconds,
            heartbeat_interval=default_uploader_op_settings.heartbeat_interval_seconds,
            file_scanner=custom_scanner,  # Check custom scanner
            file_sender=mock_sender_instance,
            fs=mock_fs_dependency,
        )
        assert returned_thread is mock_uploader_thread_instance

    @pytest.mark.parametrize(
        "failing_component_key, exception_instance, expected_log_msg_parts, "
        "expect_sender_init_attempted, expect_uploader_init_attempted",
        [
            (
                "RetryableFileSender",  # This key matches the patch target
                ValueError("Sender Init Error"),
                ["Failed to initialize RetryableFileSender", "Sender Init Error"],
                True,  # Sender init will be attempted
                False,  # UploaderThread init won't be reached if sender fails
            ),
            (
                "UploaderThread",  # This key matches the patch target
                TypeError("UploaderThread Init Error"),
                ["Failed to initialize UploaderThread", "UploaderThread Init Error"],
                True,  # Sender init must have succeeded for uploader init to be attempted
                True,  # UploaderThread init will be attempted
            ),
        ],
        ids=["retryable_sender_init_fails", "uploader_thread_init_fails"],
    )
    def test_component_initialization_failure_propagation(
        self,
        mock_resolve_validate_directory: MagicMock,
        MockRetryableFileSender: MagicMock,
        MockUploaderThread: MagicMock,
        default_uploader_op_settings: UploaderOperationalSettings,
        default_sender_conn_config: SenderConnectionConfig,
        stop_event: threading.Event,
        mock_fs_dependency: MagicMock,
        mock_http_client_dependency: MagicMock,
        caplog: pytest.LogCaptureFixture,
        failing_component_key: str,
        exception_instance: Exception,
        expected_log_msg_parts: list[str],
        expect_sender_init_attempted: bool,
        expect_uploader_init_attempted: bool,
    ):
        caplog.set_level(logging.ERROR)

        # Mock resolve_and_validate_directory to return a valid path
        # so that the factory proceeds to component instantiation.
        validated_worker_dir_mock = Path("/validated/worker_for_fail_test")
        mock_resolve_validate_directory.return_value = validated_worker_dir_mock

        constructor_mocks_map = {
            "RetryableFileSender": MockRetryableFileSender,
            "UploaderThread": MockUploaderThread,
        }

        # Set the side_effect on the constructor that should fail
        constructor_mocks_map[failing_component_key].side_effect = exception_instance

        # If UploaderThread is the one failing, RetryableFileSender should have been successfully created (mocked)
        if failing_component_key == "UploaderThread":
            # Ensure the first mock (RetryableFileSender) returns a mock instance
            # so that the factory can proceed to try and create UploaderThread.
            MockRetryableFileSender.return_value = MagicMock(spec=RetryableFileSender)

        with pytest.raises(
            type(exception_instance)
        ) as excinfo:  # Match only type for broader compatibility
            create_uploader_thread(
                uploader_op_settings=default_uploader_op_settings,
                sender_conn_config=default_sender_conn_config,
                stop_event=stop_event,
                fs=mock_fs_dependency,
                http_client=mock_http_client_dependency,
            )
        # Check if the raised exception is the one we made the mock raise
        assert excinfo.value is exception_instance

        if expect_sender_init_attempted:
            MockRetryableFileSender.assert_called_once()
        else:
            MockRetryableFileSender.assert_not_called()  # Should only happen if resolve_and_validate fails first

        if expect_uploader_init_attempted:
            MockUploaderThread.assert_called_once()
        else:
            MockUploaderThread.assert_not_called()

        assert (
            find_log_record(caplog, logging.ERROR, expected_log_msg_parts) is not None
        )
