"""
Black-Box End-to-End Tests for Data Mover Application: Scanner "Lost File" Detection.

Purpose:
--------
This test suite verifies the Data Mover application's ability to correctly
detect and process .pcap files that are present in the `source_dir` but have
not been signaled via the primary CSV mechanism and have aged beyond the
configured `lost_timeout_seconds`. These are considered "lost" files.

Primary Goals:
--------------
1.  Confirm that files placed in the `source_dir` without a corresponding CSV
    entry, and whose modification time is older than `lost_timeout_seconds`,
    are identified by the `directory_scanner` component.
2.  Verify that these identified "lost" files are correctly enqueued for
    processing.
3.  Ensure that "lost" files are subsequently moved from the `source_dir` to
    the `worker_dir`.
4.  Confirm that these files are then uploaded to the (mocked) remote HTTP
    endpoint.
5.  Verify that successfully uploaded "lost" files are finally moved to the
    `uploaded_dir`.
6.  Check for appropriate log messages indicating "lost file" detection.

Test Scope & Interactions:
--------------------------
-   **Input Simulation:**
    -   Direct creation of .pcap files in the `source_dir` with a specific (old)
      modification time.
    -   No corresponding CSV entries are created for these files, forcing reliance
      on the "lost file" detection mechanism.
-   **Application Under Test (SUT):** The entire Data Mover application,
    run via `app.run(context)`, including all its internal threads.
-   **Observed Outputs & Behaviors:**
    -   Final location of .pcap files (expected in `uploaded_dir`).
    -   Absence of processed files in `source_dir` and `worker_dir`.
    -   Log messages related to "lost file" detection.
    -   HTTP requests made to the `pytest-httpserver` instance (simulating NiFi).
-   **Environment:**
    -   Utilizes real filesystem operations within temporary directories created
      by `pytest` (`tmp_path`).
    -   The application runs with a real `Config` object, where crucial paths
      point to these temporary directories, and `remote_host_url` points to
      the local `pytest-httpserver`.
    -   Scanner timeouts (`lost_timeout_seconds`, `scanner_check_seconds`) in the
      test `Config` are set to short, testable durations.

Key Components & Their Test Status (Real vs. Mocked):
------------------------------------------------------
* **Real Components Used:**
    -   The full application stack: `Config` loading (via direct object creation
      in fixture), `FS` abstraction (using a real OS filesystem implementation),
      `app.run()`, all thread factories and their respective threads (`ScanThread`,
      `FileMoveThread`, `UploaderThread`, CSV `Tailer` components - though CSV
      tailing is not the trigger in these tests), `RetryableFileSender` with
      its configured HTTP client, and core file operation functions.
    -   The application's actual HTTP client making requests to `pytest-httpserver`.
* **Test Doubles / Controlled Environment:**
    -   **HTTP Endpoint (`pytest-httpserver`):** A local HTTP server acts as the
      NiFi endpoint, configured by tests to expect specific requests and provide
      defined responses.

Assumptions for Test Design:
----------------------------
-   The `app_test_env` fixture correctly sets up the application with a real
    filesystem interface and appropriate short timeouts for scanner operations.
-   The `directory_scanner` is the component responsible for identifying "lost"
    files.
-   Other general assumptions from the main system description document apply.
"""

import logging
import time

import pytest
from pytest_httpserver import RequestMatcher

from datamover.protocols import FS  # Or your specific import for FS type hint
from tests.test_utils.logging_helpers import find_log_record

from .conftest import BlackBoxTestEnv
from .helpers import (
    create_pcap_file_in_source_bb,
    wait_for_file_condition_bb,
)

logger = logging.getLogger(__name__)


@pytest.mark.blackbox
class TestAppScannerLostFiles:
    def test_bb_lost_file_is_scanned_and_processed(
        self,
        app_test_env: BlackBoxTestEnv,
        real_fs: FS,
        caplog: pytest.LogCaptureFixture,
    ):
        """
        Verifies that a single .pcap file, created in the source directory
        with an old modification time and no corresponding CSV entry, is
        detected as "lost" by the directory scanner, moved, successfully
        uploaded, and finally placed in the uploaded_dir.
        It also checks for the specific log message indicating "lost file" detection.
        """
        caplog.set_level(logging.DEBUG)
        test_logger = logging.getLogger(
            f"{__name__}.{self.test_bb_lost_file_is_scanned_and_processed.__name__}"
        )
        test_logger.info("Starting test: BB_SCANNER_LOST_FILE_SUCCESS")

        env = app_test_env
        nifi_target_path = env.nifi_endpoint_path_str  # Use path from environment

        lost_pcap_filename = "lost_and_found_01.pcap"
        pcap_content = b"content of a lost file"

        # Create a pcap file with an mtime old enough to be considered "lost"
        # The mtime should be older than current_time - lost_timeout_seconds.
        # Making it twice as old as lost_timeout ensures it will be picked up
        # even with slight delays in scanner execution.
        pcap_mtime = time.time() - (env.config.lost_timeout_seconds * 2)

        pcap_source_path = create_pcap_file_in_source_bb(
            env.source_dir, lost_pcap_filename, pcap_content, pcap_mtime, real_fs
        )
        test_logger.info(
            f"Created 'lost' pcap file: {pcap_source_path} (mtime: {pcap_mtime:.2f}, not added to CSV)"
        )

        # Configure the mock NiFi server to expect this file
        env.httpserver.expect_request(
            uri=nifi_target_path,
            method="POST",
            headers={
                "x-filename": lost_pcap_filename,
                "Content-Type": "application/octet-stream",
            },
            data=pcap_content,
        ).respond_with_data(
            f"Lost file {lost_pcap_filename} uploaded successfully", status=200
        )

        uploaded_file_path = env.uploaded_dir / lost_pcap_filename

        # Calculate a timeout for waiting for the file to be processed.
        # This needs to be long enough for:
        # 1. The scanner to run (controlled by scanner_check_seconds).
        # 2. The file's mtime to be older than lost_timeout_seconds.
        # 3. The scanner to identify it as lost and queue it.
        # 4. The file_mover to pick it up (move_poll_interval_seconds).
        # 5. The uploader to pick it up (uploader_poll_interval_seconds) and upload.
        processing_timeout = (
            env.config.lost_timeout_seconds
            + (
                2 * env.config.scanner_check_seconds
            )  # Allow for a couple of scan cycles
            + env.config.move_poll_interval_seconds
            + env.config.uploader_poll_interval_seconds
            + 5.0  # Generous buffer for thread scheduling and processing
        )
        test_logger.info(
            f"Waiting up to {processing_timeout:.1f}s for lost file processing "
            f"(lost_timeout_seconds: {env.config.lost_timeout_seconds}, "
            f"scanner_check_seconds: {env.config.scanner_check_seconds})"
        )

        # Wait for the file to appear in the uploaded directory
        assert wait_for_file_condition_bb(
            uploaded_file_path,
            lambda p, fs_check: fs_check.exists(p),
            real_fs,
            timeout=processing_timeout,
        ), (
            f"Lost file {lost_pcap_filename} did not appear in uploaded_dir. Logs:\n{caplog.text}"
        )
        test_logger.info(f"Lost file found in uploaded_dir: {uploaded_file_path}")

        # Shutdown the application gracefully
        test_logger.info("Initiating application shutdown for test.")
        env.shutdown_app_event.set()
        env.app_thread.join(timeout=5.0)
        assert not env.app_thread.is_alive(), (
            "Application thread did not join successfully."
        )

        # Verify final file locations: not in source or worker
        assert not real_fs.exists(pcap_source_path), (
            "Lost file was not removed from source_dir."
        )
        assert not real_fs.exists(env.worker_dir / lost_pcap_filename), (
            "Lost file was not removed from worker_dir."
        )

        # Verify content of the uploaded file
        with real_fs.open(uploaded_file_path, "rb") as f:
            assert f.read() == pcap_content, (
                "Content of uploaded lost file does not match original."
            )

        # Verify the HTTP request was made exactly once to NiFi
        env.httpserver.assert_request_made(
            RequestMatcher(
                uri=nifi_target_path,
                method="POST",
                headers={
                    "x-filename": lost_pcap_filename,
                    "Content-Type": "application/octet-stream",
                },
                data=pcap_content,
            ),
            count=1,
        )

        # Verify the specific log message indicating "lost file" detection
        expected_log_message_part = "Identified file as LOST"
        expected_logger_name = (
            "datamover.scanner.process_scan_results"  # As confirmed in previous test
        )
        lost_log_record = find_log_record(
            caplog,
            logging.INFO,
            required_substrings=[
                "Identified a new file as LOST",
                str(pcap_source_path),
            ],
        )
        assert (
            lost_log_record is not None and lost_log_record.name == expected_logger_name
        ), (
            f"Expected INFO log containing '{expected_log_message_part}' from logger '{expected_logger_name}' "
            f"for file {pcap_source_path} not found. Logs: \n{caplog.text}"
        )

        test_logger.info("Test BB_SCANNER_LOST_FILE_SUCCESS PASSED")
