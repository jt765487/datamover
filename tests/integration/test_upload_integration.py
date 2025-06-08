import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple
from unittest.mock import MagicMock

import pytest
import requests  # For requests.exceptions

# --- Application Imports ---
from datamover.file_functions.fs_mock import FS
from datamover.protocols import HttpClient, HttpResponse
from datamover.startup_code.load_config import Config
from datamover.uploader.thread_factory import (
    create_uploader_thread,
    UploaderOperationalSettings,
    SenderConnectionConfig,
)
from datamover.uploader.uploader_thread import UploaderThread
# --- Shared Test Utils ---
from tests.test_utils.fs_helpers import create_and_stamp_real_fs

# Module-level logger for this test file
logger = logging.getLogger(__name__)

# --- Constants for Integration Test ---
UPLOADER_POLL_INTERVAL = 0.02
DEFAULT_TEST_FILE_EXTENSION = "pcap"


# --- NamedTuple for Directory Structure ---
class UploaderTestDirs(NamedTuple):
    base_dir_for_test: Path  # Renamed from base_dir for clarity vs Config.base_dir
    worker_dir: Path
    uploaded_dir: Path
    dead_letter_dir: Path
    source_dir_dummy: Path
    csv_dir_dummy: Path


# --- Fixtures ---


@pytest.fixture
def uploader_test_dirs(tmp_path: Path) -> UploaderTestDirs:
    """Creates the directory structure for uploader integration tests using tmp_path."""
    base = tmp_path / "uploader_test_root"

    dirs_to_create = UploaderTestDirs(
        base_dir_for_test=base,
        worker_dir=base / "worker_for_upload",
        uploaded_dir=base / "uploaded_files",
        dead_letter_dir=base / "dead_letter_uploads",
        source_dir_dummy=base / "source_placeholder",
        csv_dir_dummy=base / "csv_placeholder",
    )
    for dir_path in dirs_to_create:
        if isinstance(dir_path, Path):
            dir_path.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created uploader integration directories: {dirs_to_create}")
    return dirs_to_create


@pytest.fixture
def integration_real_config(uploader_test_dirs: UploaderTestDirs) -> Config:
    """
    Provides a REAL Config object configured for integration tests,
    using real temporary paths from uploader_test_dirs.
    """
    # Provide ALL required fields from the Config dataclass definition
    cfg = Config(
        base_dir=uploader_test_dirs.base_dir_for_test,
        logger_dir=uploader_test_dirs.base_dir_for_test / "upload_logs",  # Added
        source_dir=uploader_test_dirs.source_dir_dummy,
        worker_dir=uploader_test_dirs.worker_dir,
        uploaded_dir=uploader_test_dirs.uploaded_dir,
        dead_letter_dir=uploader_test_dirs.dead_letter_dir,
        csv_dir=uploader_test_dirs.csv_dir_dummy,
        pcap_extension_no_dot=DEFAULT_TEST_FILE_EXTENSION,
        csv_extension_no_dot="csv",
        move_poll_interval_seconds=0.05,
        scanner_check_seconds=1.0,
        lost_timeout_seconds=300,
        stuck_active_file_timeout_seconds=400,
        event_queue_poll_timeout_seconds=0.05,
        uploader_poll_interval_seconds=UPLOADER_POLL_INTERVAL,
        heartbeat_target_interval_s=60.0,
        initial_backoff=0.01,
        max_backoff=0.05,
        remote_host_url="http://test.uploader.api/upload_endpoint",  # Renamed from remote_url
        request_timeout=2,
        verify_ssl=False,
        purger_poll_interval_seconds=3600.0,
        target_disk_usage_percent=0.75,
        total_disk_capacity_bytes=10 * 1024 ** 3,  # 10 GiB
    )
    logger.debug(f"Created real Config for integration test: {cfg}")
    return cfg


@pytest.fixture
def mock_http_client_integration() -> MagicMock:
    client = MagicMock(spec=HttpClient)
    client.post = MagicMock(name="http_client_post_method")
    return client


def create_simulated_http_response(
        status_code: int, text: str = "", headers: dict = None
) -> MagicMock:
    response = MagicMock(spec=HttpResponse)
    response.status_code = status_code
    response.text = text
    response.headers = headers if headers is not None else {}
    return response


@pytest.fixture
def uploader_test_runner_integration(
        real_fs: FS,  # Assumed from conftest.py
        integration_real_config: Config,  # Uses the new real config fixture
        mock_http_client_integration: MagicMock,
):
    created_threads: list[UploaderThread] = []

    def _setup_and_run_uploader(
            files_to_create_in_worker: dict[str, dict[str, Any]],
            http_post_side_effect: Any,
            file_extension: str = DEFAULT_TEST_FILE_EXTENSION,
            poll_interval: float = UPLOADER_POLL_INTERVAL,
    ):
        worker_dir = integration_real_config.worker_dir

        for rel_path_str, file_info in files_to_create_in_worker.items():
            full_path = worker_dir / rel_path_str
            content = file_info.get("content", b"")
            create_and_stamp_real_fs(  # Uses imported helper
                fs_operations=real_fs,
                full_path=full_path,
                size=file_info.get("size", len(content)),
                mtime=file_info.get("mtime", time.time() - 5),
                initial_create=True,
            )
            if content:
                with real_fs.open(full_path, "wb") as f:
                    f.write(content)
            logger.debug(f"TestRunner: Created/Stamped file: {full_path}")

        mock_http_client_integration.reset_mock()  # Reset BEFORE setting side_effect
        mock_http_client_integration.post.side_effect = http_post_side_effect

        stop_event = threading.Event()

        uploader_op_settings = UploaderOperationalSettings(
            worker_dir_path=integration_real_config.worker_dir,
            uploaded_dir_path=integration_real_config.uploaded_dir,
            dead_letter_dir_path=integration_real_config.dead_letter_dir,
            file_extension_to_scan=file_extension,  # Use the passed argument
            poll_interval_seconds=poll_interval,  # Use the passed argument
            heartbeat_interval_seconds=integration_real_config.heartbeat_target_interval_s,
        )

        sender_conn_config = SenderConnectionConfig(
            remote_host_url=integration_real_config.remote_host_url,
            request_timeout_seconds=integration_real_config.request_timeout,
            verify_ssl=integration_real_config.verify_ssl,
            initial_backoff_seconds=integration_real_config.initial_backoff,
            max_backoff_seconds=integration_real_config.max_backoff,
        )

        uploader_thread = create_uploader_thread(
            uploader_op_settings=uploader_op_settings,
            sender_conn_config=sender_conn_config,
            stop_event=stop_event,
            fs=real_fs,
            http_client=mock_http_client_integration,
        )

        actual_sender_instance = uploader_thread.file_sender
        processed_files_queue = queue.Queue()
        original_send_file_method = actual_sender_instance.send_file

        def wrapped_send_file(file_path_to_send: Path):
            logger.debug(
                f"TestRunner wrapped_send_file: Intercepted call for {file_path_to_send}"
            )
            assert file_path_to_send.is_absolute(), (
                "Path to send_file should be absolute"
            )
            assert file_path_to_send.parent == integration_real_config.worker_dir, (
                "Path should be in worker_dir"
            )
            result = original_send_file_method(file_path_to_send)
            processed_files_queue.put(file_path_to_send)
            logger.debug(
                f"TestRunner wrapped_send_file: {file_path_to_send} processed, result: {result}"
            )
            return result

        actual_sender_instance.send_file = wrapped_send_file

        uploader_thread.start()
        created_threads.append(uploader_thread)
        logger.info(
            f"TestRunner: Uploader thread {uploader_thread.name} started for {worker_dir}"
        )

        return uploader_thread, stop_event, processed_files_queue

    yield _setup_and_run_uploader

    logger.debug("TestRunner: Starting teardown of UploaderThread test runner.")
    for thread_idx, thread_to_stop in enumerate(
            created_threads
    ):  # Renamed 'thread' to 'thread_to_stop'
        if thread_to_stop.is_alive():
            logger.warning(
                f"TestRunner: Force stopping thread {thread_to_stop.name} (index {thread_idx}) in teardown"
            )
            # UploaderThread stores stop_event as self.stop_event
            thread_to_stop.stop_event.set()
            thread_to_stop.join(timeout=2.0)
            if thread_to_stop.is_alive():
                logger.error(
                    f"TestRunner: Thread {thread_to_stop.name} DID NOT STOP during teardown!"
                )
    logger.debug("TestRunner: Teardown complete.")


# --- Integration Test Cases ---
@pytest.mark.integration
class TestUploaderIntegration:
    @pytest.mark.parametrize(
        "http_responses_for_post, expected_post_calls, target_dir_attr_name, expected_sender_log_substr",
        [
            (
                    [create_simulated_http_response(200)],
                    1,
                    "uploaded_dir",
                    "Upload SUCCESS for",
            ),
            (
                    [create_simulated_http_response(400)],
                    1,
                    "dead_letter_dir",
                    "Moving to DEAD LETTER",
            ),
            (
                    [
                        create_simulated_http_response(503),
                        create_simulated_http_response(200),
                    ],
                    2,
                    "uploaded_dir",
                    "Upload SUCCESS for",
            ),
            (
                    [
                        requests.exceptions.Timeout("simulated timeout"),
                        create_simulated_http_response(403),
                    ],
                    2,
                    "dead_letter_dir",
                    "Moving to DEAD LETTER",
            ),
        ],
        ids=[
            "success_200",
            "fail_400_dead",
            "retry_503_then_200",
            "network_err_then_403_dead",
        ],
    )
    def test_integration_single_file_outcomes(
            self,
            # Pytest test methods in a class still take self by convention, though not strictly needed if not used
            uploader_test_runner_integration: Callable,
            integration_real_config: Config,  # Changed from integration_config
            real_fs: FS,
            mock_http_client_integration: MagicMock,
            caplog: pytest.LogCaptureFixture,
            http_responses_for_post: Any,
            expected_post_calls: int,
            target_dir_attr_name: str,
            expected_sender_log_substr: str,
            request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        caplog.set_level(logging.DEBUG)
        test_logger.info(f"Test Starting: Expected outcome -> {target_dir_attr_name}")

        file_rel_path = "test_file_single.pcap"
        files_to_create = {
            file_rel_path: {
                "content": b"single file test content",
                "mtime": time.time() - 10,
            }
        }

        uploader_thread, stop_event, processed_q = uploader_test_runner_integration(
            files_to_create_in_worker=files_to_create,
            http_post_side_effect=http_responses_for_post,
        )

        expected_abs_path = integration_real_config.worker_dir / file_rel_path
        try:
            processed_path = processed_q.get(timeout=5.0)
            assert processed_path == expected_abs_path
            test_logger.info(f"File {processed_path} confirmed processed by sender.")
        except queue.Empty:  # pragma: no cover
            pytest.fail(
                f"File {expected_abs_path} not processed within timeout. Logs:\n{caplog.text}"
            )

        test_logger.info("Requesting uploader thread stop.")
        stop_event.set()
        uploader_thread.join(timeout=2.0)
        assert not uploader_thread.is_alive(), (
            f"Uploader thread {uploader_thread.name} did not stop."
        )

        assert mock_http_client_integration.post.call_count == expected_post_calls

        target_dir = getattr(integration_real_config, target_dir_attr_name)
        final_path = target_dir / file_rel_path
        assert real_fs.exists(final_path), f"File not found in target dir {target_dir}."
        assert not real_fs.exists(integration_real_config.worker_dir / file_rel_path), (
            "Original file still in worker dir."
        )

        assert any(
            expected_sender_log_substr in rec.message
            and rec.name == "datamover.uploader.send_file_with_retries"
            for rec in caplog.records
            if rec.levelno >= logging.INFO
        ), (
            f"Expected log '{expected_sender_log_substr}' from sender not found. Logs:\n{caplog.text}"
        )
        test_logger.info("Test Finished Successfully.")

    def test_integration_move_to_done_failure_is_critical(
            self,
            uploader_test_runner_integration: Callable,
            integration_real_config: Config,  # Changed
            real_fs: FS,
            mock_http_client_integration: MagicMock,
            caplog: pytest.LogCaptureFixture,
            mocker: MagicMock,
            request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        caplog.set_level(logging.DEBUG)
        test_logger.info("Test Starting: Move to DONE fails (critical)")

        file_rel_path = "file_move_fail.pcap"
        files_to_create = {
            file_rel_path: {
                "content": b"move failure test",
                "size": 1,
                "mtime": time.time(),
            }
        }

        mocker.patch(  # No 'with', no assignment if mock object not used
            "datamover.file_functions.fs_mock.shutil.move",
            side_effect=OSError("Simulated permission denied on move"),
        )

        uploader_thread, stop_event, processed_q = uploader_test_runner_integration(
            files_to_create_in_worker=files_to_create,
            http_post_side_effect=[create_simulated_http_response(200)],
        )

        expected_abs_path = integration_real_config.worker_dir / file_rel_path
        try:
            processed_q.get(timeout=5.0)
            test_logger.info(f"File {expected_abs_path} processed (attempted move).")
        except queue.Empty:  # pragma: no cover
            pytest.fail(f"File {expected_abs_path} not processed. Logs:\n{caplog.text}")

        stop_event.set()
        uploader_thread.join(timeout=2.0)
        assert not uploader_thread.is_alive()

        mock_http_client_integration.post.assert_called_once()
        assert real_fs.exists(integration_real_config.worker_dir / file_rel_path), (
            "File should remain in worker_dir."
        )

        critical_log_found = any(
            rec.levelno == logging.CRITICAL
            and "FAILED TO MOVE TO UPLOADED DIR" in rec.message  # MODIFIED
            and str(expected_abs_path) in rec.message
            and rec.name == "datamover.uploader.send_file_with_retries"
            for rec in caplog.records
        )
        assert critical_log_found, (
            f"Expected CRITICAL log for move failure to UPLOADED dir not found. Logs:\n{caplog.text}"
        )
        test_logger.info("Test Finished Successfully.")

    def test_integration_mixed_batch_outcomes(
            self,
            uploader_test_runner_integration: Callable,
            integration_real_config: Config,  # Changed
            real_fs: FS,
            mock_http_client_integration: MagicMock,
            caplog: pytest.LogCaptureFixture,
            request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        caplog.set_level(logging.DEBUG)
        test_logger.info("Test Starting: Mixed batch of 3 files")

        time_now = time.time()
        files_data = {
            "A.pcap": {"content": b"A", "size": 10, "mtime": time_now - 30},
            "B.pcap": {"content": b"B", "size": 10, "mtime": time_now - 20},
            "C.pcap": {"content": b"C", "size": 10, "mtime": time_now - 10},
        }

        side_effect_state = {"attempts_C": 0}

        def http_post_router_side_effect(
                url: str, data: Any, headers: dict, timeout: float, verify: bool
        ):
            filename_from_header = headers.get("x-filename")
            test_logger.debug(f"HTTP_POST_ROUTER: Call for {filename_from_header}")
            if filename_from_header == "A.pcap":
                return create_simulated_http_response(200, text="A OK")
            if filename_from_header == "B.pcap":
                return create_simulated_http_response(403, text="B Forbidden")
            if filename_from_header == "C.pcap":
                side_effect_state["attempts_C"] += 1
                return create_simulated_http_response(
                    503 if side_effect_state["attempts_C"] == 1 else 200,
                    text=f"C attempt {side_effect_state['attempts_C']}",
                )
            pytest.fail(f"Unexpected filename in HTTP router: {filename_from_header}")
            return None  # pragma: no cover

        uploader_thread, stop_event, processed_q = uploader_test_runner_integration(
            files_to_create_in_worker=files_data,
            http_post_side_effect=http_post_router_side_effect,
        )

        processed_files_count = 0
        actually_processed_paths: set[Path] = set()
        deadline = time.monotonic() + 10.0  # Max wait for all files
        while processed_files_count < len(files_data) and time.monotonic() < deadline:
            try:
                processed_path = processed_q.get(timeout=0.5)
                actually_processed_paths.add(processed_path)
                processed_files_count += 1
            except queue.Empty:
                pass

        if processed_files_count < len(files_data):  # pragma: no cover
            pytest.fail(
                f"Timeout: Processed {processed_files_count}/{len(files_data)}. Logs:\n{caplog.text}"
            )

        test_logger.info(
            f"All {len(files_data)} files processed. Paths: {actually_processed_paths}"
        )
        expected_processed_paths = {
            integration_real_config.worker_dir / fn for fn in files_data.keys()
        }
        assert actually_processed_paths == expected_processed_paths

        test_logger.info("Requesting uploader thread stop.")
        stop_event.set()
        uploader_thread.join(timeout=2.0)
        assert not uploader_thread.is_alive()

        assert real_fs.exists(integration_real_config.uploaded_dir / "A.pcap")
        assert not real_fs.exists(integration_real_config.worker_dir / "A.pcap")
        assert real_fs.exists(integration_real_config.dead_letter_dir / "B.pcap")
        assert not real_fs.exists(integration_real_config.worker_dir / "B.pcap")
        assert real_fs.exists(integration_real_config.uploaded_dir / "C.pcap")
        assert not real_fs.exists(integration_real_config.worker_dir / "C.pcap")

        assert mock_http_client_integration.post.call_count == 4
        assert side_effect_state["attempts_C"] == 2
        test_logger.info("Test Finished Successfully.")

    def test_integration_empty_worker_directory_no_action(
            self,
            uploader_test_runner_integration: Callable,
            # integration_real_config: Config, # Not strictly needed if not asserting paths
            mock_http_client_integration: MagicMock,
            caplog: pytest.LogCaptureFixture,
            request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        caplog.set_level(logging.DEBUG)
        test_logger.info("Test Starting: Empty worker directory")

        files_to_create: dict[str, dict[str, Any]] = {}
        uploader_thread, stop_event, processed_q = uploader_test_runner_integration(
            files_to_create_in_worker=files_to_create, http_post_side_effect=[]
        )

        expected_min_cycles = 2  # Expect at least 2 full scan iterations
        time.sleep(
            UPLOADER_POLL_INTERVAL * (expected_min_cycles + 1.5)
        )  # Sleep a bit more
        test_logger.info(
            f"Waited for {UPLOADER_POLL_INTERVAL * (expected_min_cycles + 1.5):.2f}s."
        )

        test_logger.info("Requesting uploader thread stop.")
        stop_event.set()
        uploader_thread.join(timeout=2.0)
        assert not uploader_thread.is_alive()

        mock_http_client_integration.post.assert_not_called()
        assert processed_q.empty()

        assert hasattr(uploader_thread, "scan_cycles_completed"), (
            "UploaderThread needs 'scan_cycles_completed'"
        )
        assert uploader_thread.scan_cycles_completed >= expected_min_cycles, (
            f"Expected min {expected_min_cycles} scan cycles, got {uploader_thread.scan_cycles_completed}"
        )
        assert hasattr(uploader_thread, "files_processed_count")
        assert uploader_thread.files_processed_count == 0
        test_logger.info("Test Finished Successfully.")

    def test_integration_file_disappears_before_send(
            self,
            uploader_test_runner_integration: Callable,
            integration_real_config: Config,  # Changed
            real_fs: FS,
            mock_http_client_integration: MagicMock,
            caplog: pytest.LogCaptureFixture,
            request: pytest.FixtureRequest,
            mocker: MagicMock,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        caplog.set_level(logging.DEBUG)
        test_logger.info("Test Starting: File disappears before send attempt")

        file_rel_path = "file_to_vanish.pcap"
        files_to_create = {
            file_rel_path: {"content": b"this will vanish", "mtime": time.time() - 10}
        }
        abs_path_to_vanish = integration_real_config.worker_dir / file_rel_path

        original_os_path_exists = os.path.exists

        def new_os_path_exists_side_effect(path_str: str) -> bool:
            if Path(path_str) == abs_path_to_vanish:
                test_logger.info(
                    f"Patched os.path.exists: Simulating {abs_path_to_vanish} vanishing."
                )
                if original_os_path_exists(str(abs_path_to_vanish)):
                    try:
                        os.remove(abs_path_to_vanish)
                    except OSError as e:
                        test_logger.error(
                            f"Error removing {abs_path_to_vanish} in patch: {e}"
                        )
                return False
            return original_os_path_exists(path_str)

        # Patch where _default_exists (used by real_fs.exists) looks up os.path.exists
        mocker.patch(
            "datamover.file_functions.fs_mock.os.path.exists",
            side_effect=new_os_path_exists_side_effect,
        )

        uploader_thread, stop_event, processed_q = uploader_test_runner_integration(
            files_to_create_in_worker=files_to_create, http_post_side_effect=[]
        )

        try:
            processed_path = processed_q.get(timeout=5.0)
            assert processed_path == abs_path_to_vanish
            test_logger.info(
                f"File {processed_path} processed by sender (and vanished)."
            )
        except queue.Empty:  # pragma: no cover
            pytest.fail(
                f"File {abs_path_to_vanish} not processed. Logs:\n{caplog.text}"
            )

        test_logger.info("Requesting uploader thread stop.")
        stop_event.set()
        uploader_thread.join(timeout=2.0)
        assert not uploader_thread.is_alive()

        mock_http_client_integration.post.assert_not_called()
        assert not real_fs.exists(integration_real_config.uploaded_dir / file_rel_path)
        assert not real_fs.exists(
            integration_real_config.dead_letter_dir / file_rel_path
        )
        assert not os.path.exists(abs_path_to_vanish)

        assert any(
            "Source file" in rec.message
            and str(abs_path_to_vanish) in rec.message
            and "vanished before initial processing attempt" in rec.message
            and rec.name == "datamover.uploader.send_file_with_retries"
            and rec.levelno == logging.WARNING
            for rec in caplog.records
        ), f"Expected 'vanished' log not found. Logs:\n{caplog.text}"
        test_logger.info("Test Finished Successfully.")

    def test_integration_sender_critical_failure_handling(
            self,
            uploader_test_runner_integration: Callable,
            integration_real_config: Config,  # Changed
            real_fs: FS,
            mock_http_client_integration: MagicMock,
            caplog: pytest.LogCaptureFixture,
            mocker: MagicMock,
            request: pytest.FixtureRequest,
    ):
        test_logger = logging.getLogger(f"{request.node.nodeid}")
        caplog.set_level(logging.DEBUG)
        test_logger.info("Test Starting: Sender critical failure (move fails)")

        file_rel_path = "file_crit_fail.pcap"
        files_to_create = {
            file_rel_path: {"content": b"crit_fail_content", "mtime": time.time() - 10}
        }
        abs_worker_path = integration_real_config.worker_dir / file_rel_path

        mocker.patch(
            "datamover.file_functions.fs_mock.shutil.move",
            side_effect=OSError("FS broken for move"),
        )

        uploader_thread, stop_event, processed_q = uploader_test_runner_integration(
            files_to_create_in_worker=files_to_create,
            http_post_side_effect=[create_simulated_http_response(200)],
        )

        try:
            processed_path = processed_q.get(timeout=5.0)
            assert processed_path == abs_worker_path
            test_logger.info(
                f"File {processed_path} went through sender (expected critical failure)."
            )
        except queue.Empty:  # pragma: no cover
            pytest.fail(
                f"File {abs_worker_path} not processed by sender. Logs:\n{caplog.text}"
            )

        time.sleep(
            UPLOADER_POLL_INTERVAL * 2
        )  # Allow thread to update critically_failed_files

        test_logger.info("Requesting uploader thread stop.")
        stop_event.set()
        uploader_thread.join(timeout=2.0)
        assert not uploader_thread.is_alive()

        mock_http_client_integration.post.assert_called_once()
        assert real_fs.exists(abs_worker_path), "File should remain in worker_dir."
        assert not real_fs.exists(integration_real_config.uploaded_dir / file_rel_path)
        assert not real_fs.exists(
            integration_real_config.dead_letter_dir / file_rel_path
        )

        assert hasattr(uploader_thread, "critically_failed_files"), (
            "UploaderThread needs 'critically_failed_files'"
        )
        assert abs_worker_path in uploader_thread.critically_failed_files, (
            "File not in UploaderThread's critically_failed_files set."
        )

        assert any(
            rec.name == "datamover.uploader.uploader_thread"
            and rec.levelno == logging.ERROR
            and f"{uploader_thread.name} critical failure for file {abs_worker_path} (sender returned False)"  # <<< CORRECTED
            in rec.message
            for rec in caplog.records
        ), f"UploaderThread critical failure log not found. Logs:\n{caplog.text}"

        assert any(
            rec.levelno == logging.CRITICAL
            and "FAILED TO MOVE TO UPLOADED DIR" in rec.message
            and str(abs_worker_path) in rec.message
            and rec.name == "datamover.uploader.send_file_with_retries"
            for rec in caplog.records
        ), "Sender's CRITICAL log for failed move to DONE not found."
        test_logger.info("Test Finished Successfully.")
