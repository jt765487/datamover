# import logging
# import queue
# import threading
# import time
# from collections.abc import Callable
# from pathlib import Path
# from typing import Any, NamedTuple, Union, Optional
# from unittest.mock import MagicMock
#
# import pytest
# import requests
# from pytest_mock import MockerFixture
#
# # --- Application Imports ---
# # Assuming 'datamover' is directly importable (src is on PYTHONPATH)
# from datamover.protocols import FS as FSProtocol, HttpClient, HttpResponse
# from datamover.startup_code.load_config import Config
# from datamover.uploader.thread_factory import (
#     create_uploader_thread,
#     UploaderOperationalSettings,
#     SenderConnectionConfig,
# )
# from datamover.uploader.uploader_thread import UploaderThread
#
# # --- Shared Test Utils ---
# from tests.test_utils.fs_helpers import create_and_stamp_real_fs
# from tests.test_utils.logging_helpers import find_log_record
#
# # Module-level logger for this test file
# logger = logging.getLogger(__name__)
#
# # --- Constants for Integration Test ---
# UPLOADER_POLL_INTERVAL = 0.02  # Used by fixture and one test
# DEFAULT_TEST_FILE_EXTENSION = "pcap"
#
#
# # --- NamedTuple for Directory Structure ---
# class UploaderTestDirs(NamedTuple):
#     base_dir_for_test: Path
#     worker_dir: Path
#     uploaded_dir: Path
#     dead_letter_dir: Path
#     # Dummy dirs for Config completeness, not directly used by uploader tests
#     source_dir_dummy: Path
#     csv_dir_dummy: Path
#     config_logger_dir: Path
#
#
# # --- Fixtures ---
#
#
# @pytest.fixture
# def uploader_test_dirs(tmp_path: Path, real_fs: FSProtocol) -> UploaderTestDirs:
#     """Creates the directory structure for uploader integration tests using tmp_path and real_fs."""
#     base = tmp_path / "uploader_integration_root"
#
#     dirs = UploaderTestDirs(
#         base_dir_for_test=base,
#         worker_dir=base / "worker_for_upload",
#         uploaded_dir=base / "uploaded_files",
#         dead_letter_dir=base / "dead_letter_uploads",
#         source_dir_dummy=base / "source_placeholder",  # For Config
#         csv_dir_dummy=base / "csv_placeholder",  # For Config
#         config_logger_dir=base / "uploader_test_logs",  # For Config
#     )
#     # Iterate over the NamedTuple fields that are paths
#     for dir_path_obj in dirs:
#         if isinstance(dir_path_obj, Path):
#             real_fs.mkdir(dir_path_obj, parents=True, exist_ok=True)
#     logger.debug(f"Created uploader integration directories using real_fs: {dirs}")
#     return dirs
#
#
# @pytest.fixture
# def integration_real_config(uploader_test_dirs: UploaderTestDirs) -> Config:
#     """
#     Provides a real Config object configured for uploader integration tests,
#     using temporary paths from uploader_test_dirs.
#     """
#     cfg = Config(
#         base_dir=uploader_test_dirs.base_dir_for_test,
#         logger_dir=uploader_test_dirs.config_logger_dir,
#         source_dir=uploader_test_dirs.source_dir_dummy,
#         worker_dir=uploader_test_dirs.worker_dir,
#         uploaded_dir=uploader_test_dirs.uploaded_dir,
#         dead_letter_dir=uploader_test_dirs.dead_letter_dir,
#         csv_dir=uploader_test_dirs.csv_dir_dummy,
#         pcap_extension_no_dot=DEFAULT_TEST_FILE_EXTENSION,
#         csv_extension_no_dot="csv",
#         move_poll_interval_seconds=0.05,
#         # CRITICAL: Ensure this attribute name matches your Config class definition.
#         # Changed to 'scanner_check_seconds' assuming that's the correct name.
#         scanner_check_seconds=1.0,
#         lost_timeout_seconds=300,  # Must be < stuck_active_file_timeout_seconds
#         stuck_active_file_timeout_seconds=400,  # stuck > lost is correct
#         event_queue_poll_timeout_seconds=0.05,
#         uploader_poll_interval_seconds=UPLOADER_POLL_INTERVAL,
#         heartbeat_target_interval_s=60.0,  # Test with a very long heartbeat to avoid noise
#         initial_backoff=0.01,
#         max_backoff=0.05,
#         remote_host_url="http://mock-nifi.test/api/upload",  # Placeholder for mocked client
#         request_timeout=2.0,  # Short timeout for tests
#         verify_ssl=False,
#     )
#     logger.debug(f"Created real Config for uploader integration test: {cfg.worker_dir}")
#     return cfg
#
#
# @pytest.fixture
# def mock_http_client_integration() -> MagicMock:
#     """Provides a MagicMock for the HttpClient, suitable for integration tests."""
#     client = MagicMock(spec=HttpClient, name="MockHttpClientForUploaderIntegration")
#     # Ensure the 'post' method itself is a mock to track calls and set side_effects
#     client.post = MagicMock(name="MockHttpClientPostMethod")
#     return client
#
#
# def create_simulated_http_response(
#     status_code: int,
#     text: str = "",
#     headers: Optional[dict] = None,  # Use Optional
# ) -> MagicMock:
#     """Helper to create a mock HttpResponse object for http_client side_effects."""
#     response = MagicMock(spec=HttpResponse, name=f"MockHttpResponse_{status_code}")
#     response.status_code = status_code
#     response.text = text
#     response.headers = headers if headers is not None else {}
#     return response
#
#
# @pytest.fixture
# def uploader_test_runner_integration(
#     real_fs: FSProtocol,  # Use protocol for dependency
#     integration_real_config: Config,
#     mock_http_client_integration: MagicMock,  # This is already a MagicMock
# ):
#     """
#     A test runner fixture (factory as a fixture pattern) for UploaderThread integration.
#     Sets up and starts an UploaderThread with specified files and HTTP client behavior.
#     Yields a function that tests can call to configure and run a scenario.
#     Manages thread teardown.
#     """
#     created_threads: list[UploaderThread] = []  # Use List from typing
#
#     # This inner function is what the tests will receive and call
#     def _setup_and_run_uploader(
#         files_to_create_in_worker: dict[str, dict[str, Any]],
#         http_post_side_effect: Union[Callable, list[Any], Any],  # More specific typing
#         file_extension: str = DEFAULT_TEST_FILE_EXTENSION,
#         poll_interval: float = UPLOADER_POLL_INTERVAL,
#     ) -> tuple[UploaderThread, threading.Event, queue.Queue[Path]]:  # Return type hint
#         worker_dir = integration_real_config.worker_dir  # From outer fixture scope
#
#         # Create specified files in the worker directory using real_fs
#         for rel_path_str, file_info in files_to_create_in_worker.items():
#             full_path = worker_dir / rel_path_str
#             content: bytes = file_info.get("content", b"default_content")
#             # Use create_and_stamp_real_fs for consistent file creation
#             create_and_stamp_real_fs(
#                 fs_operations=real_fs,
#                 full_path=full_path,
#                 size=file_info.get(
#                     "size", len(content)
#                 ),  # Default to len(content) if provided
#                 mtime=file_info.get("mtime", time.time() - 5),  # Default to 5s ago
#                 initial_create=True,
#             )
#             # If specific content is provided (not just size), write it.
#             # create_and_stamp_real_fs might only create based on size with null bytes.
#             if "content" in file_info:  # Explicitly write if content key exists
#                 with real_fs.open(full_path, "wb") as f:
#                     f.write(content)
#             logger.debug(f"TestRunner: Prepared file in worker: {full_path}")
#
#         # Reset mock and set side effect for HTTP client's post method for this run
#         mock_http_client_integration.reset_mock()
#         mock_http_client_integration.post.side_effect = http_post_side_effect
#
#         stop_event = threading.Event()
#
#         # Configure UploaderThread settings
#         uploader_op_settings = UploaderOperationalSettings(
#             worker_dir_path=integration_real_config.worker_dir,
#             uploaded_dir_path=integration_real_config.uploaded_dir,
#             dead_letter_dir_path=integration_real_config.dead_letter_dir,
#             file_extension_to_scan=file_extension,
#             poll_interval_seconds=poll_interval,
#             heartbeat_interval_seconds=integration_real_config.heartbeat_target_interval_s,
#         )
#
#         sender_conn_config = SenderConnectionConfig(
#             remote_host_url=integration_real_config.remote_host_url,
#             request_timeout_seconds=integration_real_config.request_timeout,
#             verify_ssl=integration_real_config.verify_ssl,
#             initial_backoff_seconds=integration_real_config.initial_backoff,
#             max_backoff_seconds=integration_real_config.max_backoff,
#         )
#
#         # Create UploaderThread using the application's factory
#         uploader_thread = create_uploader_thread(
#             uploader_op_settings=uploader_op_settings,
#             sender_conn_config=sender_conn_config,
#             stop_event=stop_event,
#             fs=real_fs,  # Pass the real FS
#             http_client=mock_http_client_integration,  # Pass the mocked HTTP client
#         )
#
#         # Wrap the sender's send_file method to monitor processed files via a queue
#         actual_sender_instance = uploader_thread.file_sender
#         processed_files_queue: queue.Queue[Path] = queue.Queue()
#         original_send_file_method = actual_sender_instance.send_file
#
#         def wrapped_send_file(file_path_to_send: Path) -> bool:
#             logger.debug(f"TestRunner intercepted send_file for: {file_path_to_send}")
#             # Sanity checks for the path being processed by the sender
#             assert file_path_to_send.is_absolute(), (
#                 "Path to send_file must be absolute."
#             )
#             assert file_path_to_send.parent == integration_real_config.worker_dir, (
#                 "File being sent by sender should originate from the worker_dir."
#             )
#
#             result = original_send_file_method(file_path_to_send)
#             processed_files_queue.put(
#                 file_path_to_send
#             )  # Signal that processing is complete
#             logger.debug(
#                 f"TestRunner: {file_path_to_send.name} processed by sender, result: {result}"
#             )
#             return result
#
#         actual_sender_instance.send_file = wrapped_send_file
#
#         uploader_thread.start()
#         created_threads.append(uploader_thread)
#         logger.info(
#             f"TestRunner: Uploader thread '{uploader_thread.name}' started, watching '{worker_dir}'."
#         )
#
#         return uploader_thread, stop_event, processed_files_queue
#
#     yield _setup_and_run_uploader  # Provide the setup function to the tests
#
#     # Teardown: ensure all created threads are stopped
#     logger.debug("TestRunner: Tearing down uploader threads created by test runner.")
#     for idx, thread in enumerate(created_threads):
#         if thread.is_alive():  # pragma: no cover (should be stopped by tests ideally)
#             logger.warning(
#                 f"TestRunner Teardown: Forcing stop for thread '{thread.name}' (index {idx})."
#             )
#             if hasattr(thread, "stop_event") and isinstance(
#                 thread.stop_event, threading.Event
#             ):
#                 thread.stop_event.set()
#             thread.join(timeout=2.0)
#             if thread.is_alive():
#                 logger.error(
#                     f"TestRunner Teardown: Thread '{thread.name}' DID NOT STOP."
#                 )
#     logger.debug("TestRunner: Teardown complete.")
#
#
# # --- Integration Test Cases ---
# @pytest.mark.integration  # Ensure this marker is registered in pyproject.toml
# class TestUploaderIntegration:
#     """
#     Integration tests for the UploaderThread and its interaction with RetryableFileSender,
#     using a real filesystem and a mocked HttpClient.
#     Focuses on file outcomes based on simulated HTTP responses.
#     """
#
#     @pytest.mark.parametrize(
#         "http_responses_for_post, expected_post_calls, target_dir_key, expected_final_log_info",
#         [
#             (
#                 [create_simulated_http_response(200, text="Upload OK")],
#                 1,
#                 "uploaded_dir",
#                 {
#                     "level": logging.INFO,
#                     "substr": "Upload SUCCESS for",
#                     "logger": "datamover.uploader.send_file_with_retries",
#                 },
#             ),
#             (
#                 [create_simulated_http_response(400, text="Bad Request")],
#                 1,
#                 "dead_letter_dir",
#                 {
#                     "level": logging.ERROR,
#                     "substr": "Moving to DEAD LETTER",
#                     "logger": "datamover.uploader.send_file_with_retries",
#                 },
#             ),
#             (
#                 [  # Sequence: 503 (retryable), then 200 (success)
#                     create_simulated_http_response(503, text="Service Unavailable"),
#                     create_simulated_http_response(200, text="Upload OK after retry"),
#                 ],
#                 2,  # Two HTTP POST calls expected
#                 "uploaded_dir",
#                 {
#                     "level": logging.INFO,
#                     "substr": "Upload SUCCESS for",
#                     "logger": "datamover.uploader.send_file_with_retries",
#                 },
#             ),
#             (
#                 [  # Sequence: Network Timeout, then 403 (terminal)
#                     requests.exceptions.Timeout("Simulated network timeout"),
#                     create_simulated_http_response(403, text="Forbidden"),
#                 ],
#                 2,  # HttpClient.post called twice; first raises Timeout, second gets 403
#                 "dead_letter_dir",
#                 {
#                     "level": logging.ERROR,
#                     "substr": "Moving to DEAD LETTER",
#                     "logger": "datamover.uploader.send_file_with_retries",
#                 },
#             ),
#         ],
#         ids=[
#             "success_200_OK",
#             "terminal_failure_400_to_dead_letter",
#             "retry_on_503_then_success_200",
#             "network_error_retry_then_terminal_403_to_dead_letter",
#         ],
#     )
#     def test_integration_single_file_outcomes(
#         self,
#         uploader_test_runner_integration: Callable[
#             ..., tuple[UploaderThread, threading.Event, queue.Queue[Path]]
#         ],
#         integration_real_config: Config,
#         real_fs: FSProtocol,
#         mock_http_client_integration: MagicMock,  # For asserting calls
#         caplog: pytest.LogCaptureFixture,
#         http_responses_for_post: list[Any],  # List of responses or exceptions
#         expected_post_calls: int,
#         target_dir_key: str,  # Key to get directory from integration_real_config
#         expected_final_log_info: dict[str, Any],
#         request: pytest.FixtureRequest,  # For unique logger name
#     ):
#         """
#         Tests various outcomes for a single file processed by the uploader,
#         based on different sequences of HTTP responses from the mocked HttpClient.
#         """
#         test_logger = logging.getLogger(
#             f"{request.node.nodeid}"
#         )  # Unique logger per test case
#         caplog.set_level(logging.DEBUG)
#         test_logger.info(
#             f"Test Starting: Scenario -> {request.node.callspec.id if hasattr(request.node, 'callspec') else 'unknown_scenario'}"
#         )
#
#         file_rel_path = "test_single_outcome.pcap"
#         file_content = b"single file content for outcome test"
#         files_to_create = {
#             file_rel_path: {"content": file_content, "mtime": time.time() - 10}
#         }
#         abs_worker_path = integration_real_config.worker_dir / file_rel_path
#
#         # Setup and start the uploader thread for this scenario
#         uploader_thread, stop_event, processed_q = uploader_test_runner_integration(
#             files_to_create_in_worker=files_to_create,
#             http_post_side_effect=http_responses_for_post,  # This will be a list of responses/exceptions
#         )
#
#         # Wait for the file to be processed by the sender (i.e., send_file wrapper put it on queue)
#         try:
#             processed_path = processed_q.get(
#                 timeout=10.0
#             )  # Generous timeout for all retries
#             assert processed_path == abs_worker_path, "Processed path mismatch"
#             test_logger.info(
#                 f"File '{processed_path.name}' confirmed processed by sender logic."
#             )
#         except queue.Empty:  # pragma: no cover
#             pytest.fail(
#                 f"File '{abs_worker_path.name}' was not processed by the sender within timeout. "
#                 f"HTTP Client Post Calls: {mock_http_client_integration.post.call_count}. "
#                 f"Logs:\n{caplog.text}"
#             )
#
#         # Request thread to stop and wait for it to finish
#         test_logger.info(
#             f"Requesting uploader thread '{uploader_thread.name}' to stop."
#         )
#         stop_event.set()
#         uploader_thread.join(timeout=5.0)  # Increased join timeout for safety
#         assert not uploader_thread.is_alive(), (
#             f"Uploader thread '{uploader_thread.name}' did not stop."
#         )
#
#         # Verify the number of HTTP POST attempts
#         assert mock_http_client_integration.post.call_count == expected_post_calls, (
#             "Mismatch in expected HTTP POST call count."
#         )
#
#         # Verify final file location
#         target_dir_path = getattr(integration_real_config, target_dir_key)
#         final_file_path = target_dir_path / file_rel_path
#
#         assert real_fs.exists(final_file_path), (
#             f"File '{file_rel_path}' not found in expected target directory '{target_dir_path}'."
#         )
#         assert not real_fs.exists(abs_worker_path), (
#             f"File '{file_rel_path}' should not remain in worker directory '{integration_real_config.worker_dir}'."
#         )
#
#         # Verify content if it ended up in uploaded_dir
#         if target_dir_key == "uploaded_dir":
#             with real_fs.open(final_file_path, "rb") as f:
#                 assert f.read() == file_content, "Uploaded file content does not match."
#
#         # Verify key log message indicating the outcome
#         log_record = find_log_record(
#             caplog,
#             expected_final_log_info["level"],
#             required_substrings=[expected_final_log_info["substr"], file_rel_path],
#             logger_name_filter=expected_final_log_info["logger"],
#         )
#         assert log_record is not None, (
#             f"Expected log with substring '{expected_final_log_info['substr']}' from logger "
#             f"'{expected_final_log_info['logger']}' not found. Logs:\n{caplog.text}"
#         )
#
#         test_logger.info(
#             f"Test Scenario '{request.node.callspec.id if hasattr(request.node, 'callspec') else ''}' PASSED."
#         )
#
#     def test_integration_move_to_done_failure_is_critical(
#         self,
#         uploader_test_runner_integration: Callable[
#             ..., tuple[UploaderThread, threading.Event, queue.Queue[Path]]
#         ],
#         integration_real_config: Config,
#         real_fs: FSProtocol,
#         mock_http_client_integration: MagicMock,
#         caplog: pytest.LogCaptureFixture,
#         mocker: MockerFixture,  # Corrected type hint
#         request: pytest.FixtureRequest,
#     ):
#         test_logger = logging.getLogger(f"{request.node.nodeid}")
#         caplog.set_level(logging.DEBUG)
#         test_logger.info(
#             "Test Starting: Uploader handles critical failure when move to UPLOADED dir fails."
#         )
#
#         file_rel_path = "file_move_to_uploaded_fail.pcap"
#         abs_worker_path = integration_real_config.worker_dir / file_rel_path
#         files_to_create = {
#             file_rel_path: {
#                 "content": b"content for move-to-uploaded-fail test",
#                 "mtime": time.time(),
#             }
#         }
#
#         # Mock shutil.move (used by real_fs.move via _default_move) to simulate failure
#         # Ensure this patch target is correct for how your real_fs.move is implemented.
#         # If real_fs.move directly calls path.rename, you'd patch "pathlib.Path.rename".
#         mocker.patch(
#             "datamover.file_functions.fs_mock.shutil.move",  # Path to where shutil.move is called by _default_move
#             side_effect=OSError("Simulated OS error during move to uploaded_dir"),
#         )
#
#         # Setup uploader: HTTP POST will succeed, but subsequent move to uploaded_dir will fail
#         uploader_thread, stop_event, processed_q = uploader_test_runner_integration(
#             files_to_create_in_worker=files_to_create,
#             http_post_side_effect=[
#                 create_simulated_http_response(200, text="Upload OK, move will fail")
#             ],
#         )
#
#         # Wait for the file to be processed by the sender logic
#         try:
#             processed_file_path = processed_q.get(
#                 timeout=5.0
#             )  # Sender.send_file will return False
#             assert processed_file_path == abs_worker_path
#             test_logger.info(
#                 f"File '{processed_file_path.name}' confirmed processed by sender (expected to return False)."
#             )
#         except queue.Empty:  # pragma: no cover
#             pytest.fail(
#                 f"File '{abs_worker_path.name}' was not processed by sender within timeout. Logs:\n{caplog.text}"
#             )
#
#         # Allow a moment for UploaderThread to react to sender returning False
#         time.sleep(UPLOADER_POLL_INTERVAL * 2)
#
#         # Stop the thread
#         test_logger.info("Requesting uploader thread stop.")
#         stop_event.set()
#         uploader_thread.join(timeout=2.0)
#         assert not uploader_thread.is_alive(), (
#             f"Uploader thread '{uploader_thread.name}' did not stop."
#         )
#
#         # Assertions
#         mock_http_client_integration.post.assert_called_once()  # Upload attempt should have happened
#         assert real_fs.exists(abs_worker_path), (
#             "File should remain in worker_dir after failed move to uploaded."
#         )
#         assert not real_fs.exists(
#             integration_real_config.uploaded_dir / file_rel_path
#         ), "File should NOT be in uploaded_dir."
#         assert not real_fs.exists(
#             integration_real_config.dead_letter_dir / file_rel_path
#         ), "File should NOT be in dead_letter_dir."
#
#         # Check for the CRITICAL log from RetryableFileSender about the move failure
#         sender_critical_log = find_log_record(
#             caplog,
#             logging.CRITICAL,
#             required_substrings=["FAILED TO MOVE TO UPLOADED DIR", file_rel_path],
#             logger_name_filter="datamover.uploader.send_file_with_retries",
#         )
#         assert sender_critical_log is not None, (
#             f"Expected sender's CRITICAL log for failed move to UPLOADED dir not found. Logs:\n{caplog.text}"
#         )
#
#         # Check for the ERROR log from UploaderThread because sender returned False
#         uploader_error_log = find_log_record(
#             caplog,
#             logging.ERROR,
#             required_substrings=[
#                 uploader_thread.name,
#                 "critical failure for file",
#                 str(abs_worker_path),
#                 "(sender returned False)",
#             ],
#             logger_name_filter="datamover.uploader.uploader_thread",
#         )
#         assert uploader_error_log is not None, (
#             f"Expected UploaderThread ERROR log for sender returning False not found. Logs:\n{caplog.text}"
#         )
#
#         # Check if file is in uploader_thread.critically_failed_files
#         assert hasattr(uploader_thread, "critically_failed_files"), (
#             "UploaderThread needs 'critically_failed_files' attribute for this test."
#         )
#         assert abs_worker_path in uploader_thread.critically_failed_files, (
#             f"File '{abs_worker_path.name}' not found in UploaderThread's critically_failed_files set."
#         )
#
#         test_logger.info(
#             "Test Finished Successfully: Critical failure on move to UPLOADED dir handled."
#         )
#
#     # ... (test_integration_mixed_batch_outcomes - apply similar refinements if needed, especially to http_post_router_side_effect for clarity and log checks) ...
#     # ... (test_integration_empty_worker_directory_no_action - ensure UPLOADER_POLL_INTERVAL is used from test constant) ...
#     # ... (test_integration_file_disappears_before_send - check patch target, use MockerFixture) ...
#     # ... (test_integration_sender_critical_failure_handling was the one that failed, ensure the log message matches)
