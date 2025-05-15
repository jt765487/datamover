import logging
import queue
import threading
import time
from pathlib import Path
from typing import NamedTuple

import pytest
from datamover.mover.thread_factory import create_file_move_thread

from datamover.file_functions.fs_mock import FS
from datamover.startup_code.load_config import Config

# Logger for the test module
logger = logging.getLogger(__name__)


class FileMoverTestEnv(NamedTuple):
    config: Config
    source_dir: Path
    worker_dir: Path
    dummy_file_source_path: Path
    fs: FS
    stop_event: threading.Event


@pytest.fixture
def file_mover_test_env(
    tmp_path: Path, real_fs: FS, request: pytest.FixtureRequest
) -> FileMoverTestEnv:
    """
    Sets up a self-contained test environment for FileMoveThread integration tests
    using a real filesystem.
    """
    fixture_logger = logging.getLogger(f"{__name__}.{request.node.name}.fixture")
    fixture_logger.debug(f"Setting up FileMoverTestEnv in base temp dir: {tmp_path}")

    base_dir_for_test = tmp_path / "fm_integration_base"
    source_dir = base_dir_for_test / "source_data"
    worker_dir = base_dir_for_test / "worker_data"
    # Other dirs needed for Config instantiation, even if not directly used by FileMover
    uploaded_dir = base_dir_for_test / "uploaded_data"
    dead_letter_dir = base_dir_for_test / "dead_letter_data"
    csv_dir = base_dir_for_test / "csv_data"
    config_logger_dir = base_dir_for_test / "fm_test_logs"

    # Create directories using the injected real_fs
    for d in [
        source_dir,
        worker_dir,
        uploaded_dir,
        dead_letter_dir,
        csv_dir,
        config_logger_dir,
        base_dir_for_test,  # Ensure base is also created if not covered by parents=True
    ]:
        real_fs.mkdir(d, parents=True, exist_ok=True)
        fixture_logger.debug(f"Created directory via real_fs: {d}")

    dummy_file_name = "fm_integration_test_file.txt"
    dummy_file_source_path = source_dir / dummy_file_name

    # Create a Config object tailored for these integration tests
    config = Config(
        base_dir=base_dir_for_test,
        logger_dir=config_logger_dir,  # Use the created logger dir
        source_dir=source_dir,
        worker_dir=worker_dir,
        uploaded_dir=uploaded_dir,  # Required by Config
        dead_letter_dir=dead_letter_dir,  # Required by Config
        csv_dir=csv_dir,  # Required by Config
        pcap_extension_no_dot="pcap",
        csv_extension_no_dot="csv",
        move_poll_interval_seconds=0.05,  # Short for responsive testing
        # scaner_check_seconds is critical: ensure this matches your Config class definition
        # If your Config class expects 'scanner_check_seconds', change it here.
        scanner_check_seconds=1.0,  # Less critical for isolated mover test, but must be valid
        lost_timeout_seconds=30,  # Must be < stuck_active_file_timeout_seconds
        stuck_active_file_timeout_seconds=60,
        event_queue_poll_timeout_seconds=0.05,
        uploader_poll_interval_seconds=0.05,
        heartbeat_target_interval_s=60.0,
        remote_host_url="http://fake-nifi-for-config-only.example.com",  # Placeholder
        request_timeout=5.0,
        verify_ssl=False,
        initial_backoff=0.1,
        max_backoff=1.0,
    )

    stop_event = threading.Event()

    fixture_logger.debug(
        f"Fixture setup complete. Config source: {config.source_dir}, worker: {config.worker_dir}"
    )
    return FileMoverTestEnv(
        config=config,
        source_dir=source_dir,
        worker_dir=worker_dir,
        dummy_file_source_path=dummy_file_source_path,
        fs=real_fs,  # Pass the injected real_fs
        stop_event=stop_event,
    )


@pytest.mark.integration  # Remember to register this marker in pyproject.toml
class TestFileMoverIntegration:
    """
    Integration tests for the FileMoveThread.
    These tests use real file system operations via the 'real_fs' fixture
    to verify the thread's core responsibility of moving files from a source
    queue to a worker directory.
    """

    def test_file_is_moved_successfully(
        self,
        file_mover_test_env: FileMoverTestEnv,
        caplog: pytest.LogCaptureFixture,
        request: pytest.FixtureRequest,
    ):
        """
        Tests the happy path: a file path placed on the source queue is
        successfully picked up by the FileMoveThread and moved from the
        source_dir to the worker_dir.
        """
        test_logger = logging.getLogger(f"{request.node.name}")  # Simpler logger name
        caplog.set_level(logging.DEBUG)
        test_logger.info("Starting test: File successfully moved by FileMoveThread")

        env = file_mover_test_env

        # Arrange: Create a dummy file in the source directory using the injected FS
        file_content = "Content for FileMover integration test."
        # Ensure the source file is created using the FS abstraction from the environment
        with env.fs.open(env.dummy_file_source_path, "w") as f:
            f.write(file_content)
        assert env.fs.exists(env.dummy_file_source_path), (
            "Test setup: Source file was not created."
        )
        test_logger.debug(
            f"Test setup: Created source file: {env.dummy_file_source_path}"
        )

        # The queue that FileMoveThread will listen to
        source_queue: queue.Queue[Path] = queue.Queue()

        # Create and start the file move thread using the application's factory
        file_move_thread = create_file_move_thread(
            source_dir_path=env.config.source_dir,
            worker_dir_path=env.config.worker_dir,
            poll_interval_seconds=env.config.move_poll_interval_seconds,
            source_queue=source_queue,
            stop_event=env.stop_event,
            fs=env.fs,
        )

        # Put the path of the file to be moved onto the queue
        source_queue.put(env.dummy_file_source_path)
        test_logger.info(
            f"Test action: Put '{env.dummy_file_source_path.name}' on the source_queue."
        )

        file_move_thread.start()
        test_logger.info(f"Test action: Thread '{file_move_thread.name}' started.")

        # Act: Wait for the queue to be processed by the thread
        # This relies on FileMoveThread calling task_done() on the queue item.
        processing_timeout = 5.0  # seconds
        deadline = time.monotonic() + processing_timeout
        item_processed_successfully = False

        while time.monotonic() < deadline:
            if source_queue.unfinished_tasks == 0:
                item_processed_successfully = True
                break
            time.sleep(0.05)  # Poll frequently

        assert item_processed_successfully, (
            f"Queue item for '{env.dummy_file_source_path.name}' was not processed by thread within {processing_timeout}s. "
            f"Queue empty: {source_queue.empty()}, Unfinished tasks: {source_queue.unfinished_tasks}"
        )
        test_logger.debug("Test check: source_queue processing appears complete.")

        # Assert: Verify file movement and queue state
        assert source_queue.empty(), (
            "Source queue should be empty after successful processing."
        )

        # Stop the thread
        test_logger.info("Test action: Requesting FileMoveThread to stop.")
        env.stop_event.set()
        file_move_thread.join(timeout=2.0)
        assert not file_move_thread.is_alive(), (
            f"Thread '{file_move_thread.name}' did not stop in time."
        )
        test_logger.info(f"Test check: Thread '{file_move_thread.name}' stopped.")

        # Verify file locations and content
        final_worker_path = env.worker_dir / env.dummy_file_source_path.name
        assert not env.fs.exists(env.dummy_file_source_path), (
            f"Source file '{env.dummy_file_source_path}' should no longer exist."
        )
        assert env.fs.exists(final_worker_path), (
            f"Target file '{final_worker_path}' in worker directory was not created."
        )
        test_logger.debug(f"Test check: File confirmed moved to: {final_worker_path}")

        with env.fs.open(final_worker_path, "r") as f_worker:
            content_in_worker = f_worker.read()
        assert content_in_worker == file_content, (
            "File content mismatch in worker directory."
        )

        test_logger.info(
            "Test '{request.node.name}' PASSED: File moved and content verified."
        )

    @pytest.mark.integration
    def test_thread_exits_quickly_if_stop_event_pre_set(
        self,
        file_mover_test_env: FileMoverTestEnv,
        caplog: pytest.LogCaptureFixture,  # caplog might not be strictly needed if not asserting logs
        request: pytest.FixtureRequest,
    ):
        """
        Tests that the FileMoveThread exits quickly without processing an item
        from the queue if its stop_event is set before the thread can process it.
        """
        test_logger = logging.getLogger(f"{request.node.name}")
        caplog.set_level(logging.DEBUG)  # Keep for diagnosability
        test_logger.info(
            "Starting test: FileMoveThread exits quickly with pre-set stop_event"
        )

        env = file_mover_test_env

        # Arrange: Create a dummy file and put its path on the queue
        with env.fs.open(env.dummy_file_source_path, "w") as f:
            f.write("This file should not be moved if thread stops early.")
        assert env.fs.exists(env.dummy_file_source_path)
        test_logger.debug(
            f"Test setup: Created source file: {env.dummy_file_source_path}"
        )

        source_queue: queue.Queue[Path] = queue.Queue()
        source_queue.put(env.dummy_file_source_path)
        test_logger.debug(
            f"Test setup: Put '{env.dummy_file_source_path.name}' on source_queue."
        )

        # Pre-set the stop event *before* creating/starting the thread
        env.stop_event.set()
        test_logger.info("Test setup: stop_event has been pre-set.")

        file_move_thread = create_file_move_thread(
            source_dir_path=env.config.source_dir,
            worker_dir_path=env.config.worker_dir,
            poll_interval_seconds=env.config.move_poll_interval_seconds,  # Very short poll
            source_queue=source_queue,
            stop_event=env.stop_event,
            fs=env.fs,
        )

        # Act: Start the thread and measure its exit time
        start_time = time.monotonic()
        file_move_thread.start()
        test_logger.info(
            f"Test action: Thread '{file_move_thread.name}' started with stop_event pre-set."
        )

        file_move_thread.join(
            timeout=1.0
        )  # Give a short time for the thread to notice event and exit
        duration = time.monotonic() - start_time
        test_logger.info(
            f"Test check: Thread join attempt completed in {duration:.4f} seconds."
        )

        # Assert: Verify thread stopped quickly and the file was not moved
        assert not file_move_thread.is_alive(), (
            f"Thread '{file_move_thread.name}' did not stop quickly with pre-set stop_event."
        )
        # Duration check: should be very short, mostly thread overhead
        # Poll interval is 0.05s, so it should check stop event quickly.
        assert duration < (env.config.move_poll_interval_seconds * 3), (
            f"Thread took too long ({duration:.4f}s) to exit with pre-set stop event."
        )

        # Assert item was not processed from the queue
        assert not source_queue.empty(), (
            "Queue should not be empty as item should not have been processed."
        )
        # If thread exits before get() or after get() but before task_done()
        assert source_queue.unfinished_tasks == 1, (
            f"Queue should still have 1 unfinished task, but has {source_queue.unfinished_tasks}."
        )

        # Verify file was not moved
        assert env.fs.exists(env.dummy_file_source_path), (
            "Source file should still exist as it was not processed."
        )
        final_worker_path = env.worker_dir / env.dummy_file_source_path.name
        assert not env.fs.exists(final_worker_path), (
            "Worker file should not exist as item was not processed."
        )

        test_logger.info(
            "Test '{request.node.name}' PASSED: Thread exited quickly, no file processing occurred."
        )
