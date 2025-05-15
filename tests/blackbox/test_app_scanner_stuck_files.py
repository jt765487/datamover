"""
Black-Box End-to-End Integration Tests for the Data Mover Application:
Scanner Stuck and Lost File Scenarios.

Purpose:
--------
This test file verifies the application's ability to correctly handle .pcap files
in the source_dir that are initially "stuck" (actively being written to) and
subsequently become "lost" (inactive for a configured period).

The primary goal is to confirm that:
1. Files actively being modified (simulated by mtime updates) beyond the
   `scanner_stuck_active_file_timeout_seconds` are correctly identified as
   "stuck active" and are NOT processed prematurely.
2. Once modifications cease, and after `scanner_lost_timeout_seconds` elapses,
   these files are then correctly identified as "lost."
3. "Lost" files (originating from a "stuck active" state) are then processed
   through the standard pipeline: moved to worker_dir, uploaded to the remote
   HTTP endpoint, and finally placed in the uploaded_dir.

Test Scope & Interactions:
--------------------------
- **Input Simulation:**
    - Creation of .pcap files in the `source_dir`.
    - Continuous modification of a .pcap file's mtime to simulate active writing,
      triggering "stuck active" detection.
    - Cessation of mtime updates to allow the file to transition to "lost."
- **Application Under Test (SUT):** The entire Data Mover application, started
  via its main `run(context)` function. This includes all its internal threads.
- **Observed Outputs & Behaviors:**
    - File disposition during the "stuck active" phase (should remain in source_dir).
    - Final location of .pcap files (in `uploaded_dir` after becoming "lost"
      and processed).
    - Absence of processed files in `source_dir` and `worker_dir` post-processing.
    - Calls made to the `pytest-httpserver` instance.
- **Environment:**
    - Real filesystem operations within temporary directories (`tmp_path`).
    - Real application `Config` objects, with `remote_url` pointing to the
      `pytest-httpserver` instance. Configurable timeouts for scanner behaviors
      are crucial.
    - Real time for operational delays and timeouts.

Key Components & Their Test Status (Real vs. Mocked):
------------------------------------------------------
* **Real Components Used:** Same as other black-box tests (Config, FS, app.run(),
  all threads, actual HTTP client).
* **Test Doubles / Controlled Environment:**
    - **HTTP Endpoint (`pytest-httpserver`):** Simulates the remote NiFi endpoint.

Assumptions for Test Design:
----------------------------
- The application's `build_context` correctly sets up all components.
- `config.scanner_stuck_active_file_timeout_seconds` and
  `config.scanner_lost_timeout_seconds` are configured to testable (short) durations.
"""

import logging
import time

import pytest
from pytest_httpserver import RequestMatcher

from datamover.file_functions.fs_mock import FS
from .conftest import BlackBoxTestEnv
from .helpers import (
    create_pcap_file_in_source_bb,
    wait_for_file_condition_bb,
)
from ..test_utils.fs_helpers import create_and_stamp_real_fs
from ..test_utils.logging_helpers import find_log_record

logger = logging.getLogger(__name__)


@pytest.mark.blackbox
class TestAppScannerStuckAndLostFiles:
    def test_bb_stuck_file_becomes_lost_and_processed(
        self,
        app_test_env: BlackBoxTestEnv,
        real_fs: FS,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)
        test_logger = logging.getLogger(
            f"{__name__}.{self.test_bb_stuck_file_becomes_lost_and_processed.__name__}"
        )
        test_logger.info("Starting test: BB_SCANNER_STUCK_THEN_LOST_SUCCESS")

        env = app_test_env
        pcap_filename = "stuck_then_lost_file_01.pcap"
        pcap_content = b"This file will be stuck, then lost, then found."

        # Use the NIFI endpoint path from the environment fixture for consistency
        nifi_target_path = env.nifi_endpoint_path_str

        # Get critical timeouts from the test environment's config
        scan_interval = (
            env.config.scanner_check_seconds
        )  # Note "scaner" typo if still in Config
        stuck_timeout = env.config.stuck_active_file_timeout_seconds
        lost_timeout = env.config.lost_timeout_seconds

        test_logger.info(
            f"Test configured with: scan_interval={scan_interval}s, "
            f"stuck_timeout={stuck_timeout}s, lost_timeout={lost_timeout}s. "
            f"NiFi path: {nifi_target_path}"
        )

        # 1. Initial file creation in source_dir
        # Create it with an mtime that's not immediately "lost" but will be updated.
        initial_mtime = time.time() - (stuck_timeout / 2)
        pcap_source_path = create_pcap_file_in_source_bb(
            env.source_dir, pcap_filename, pcap_content, initial_mtime, real_fs
        )
        test_logger.info(
            f"Created initial pcap file: {pcap_source_path} at mtime {initial_mtime:.2f}"
        )

        # 2. Simulate "Stuck Active" Phase
        # Continuously update mtime for a duration > stuck_timeout.
        # Updates must occur between scanner runs for the "active" part of "stuck active".
        # Duration of simulation: stuck_timeout + a couple of scan_intervals to ensure detection.
        stuck_simulation_duration = (
            stuck_timeout + (2 * scan_interval) + 0.1
        )  # a bit extra
        update_step_interval = (
            scan_interval * 0.75
        )  # Update more frequently than scans to ensure activity detected

        test_logger.info(
            f"Simulating 'stuck active' phase for ~{stuck_simulation_duration:.2f}s "
            f"by updating mtime every {update_step_interval:.2f}s."
        )

        stuck_phase_end_mono_time = time.monotonic() + stuck_simulation_duration
        last_simulated_mtime = initial_mtime
        update_counter = 0

        while time.monotonic() < stuck_phase_end_mono_time:
            # Ensure application is still running
            if (
                not env.app_thread.is_alive() or env.shutdown_app_event.is_set()
            ):  # pragma: no cover
                pytest.fail(
                    "Application thread stopped unexpectedly during stuck active simulation."
                )

            last_simulated_mtime = time.time()  # Get a fresh timestamp for each update
            # Use create_and_stamp_real_fs to update mtime.
            # initial_create=False ensures it modifies an existing file.
            create_and_stamp_real_fs(
                real_fs,
                pcap_source_path,
                len(pcap_content),
                last_simulated_mtime,
                initial_create=False,
            )
            update_counter += 1
            test_logger.debug(
                f"Updated mtime for {pcap_filename} to {last_simulated_mtime:.2f} (Update #{update_counter})"
            )
            time.sleep(update_step_interval)

        test_logger.info(
            f"Completed {update_counter} mtime updates. Last mtime: {last_simulated_mtime:.2f}. Waiting for stuck log."
        )

        # Wait a *short* time, enough for the scanner to process the last "active" state
        # and for the ScanThread to emit its CRITICAL log if the file is newly stuck.
        time.sleep(scan_interval * 0.5)  # e.g., 0.2s * 0.5 = 0.1s

        # Assert "STUCK ACTIVE" CRITICAL log (from ScanThread)
        # The README indicates ScanThread emits a CRITICAL log for newly stuck files.
        stuck_log = find_log_record(
            caplog,
            logging.CRITICAL,
            required_substrings=[
                "STUCK ACTIVE files",
                str(pcap_source_path),
            ],  # Message check
        )
        assert (
            stuck_log is not None and stuck_log.name == "datamover.scanner.scan_thread"
        ), (
            f"Expected CRITICAL 'STUCK ACTIVE files' log from 'datamover.scanner.scan_thread' "
            f"for '{pcap_source_path}' not found. Logs:\n{caplog.text}"
        )
        test_logger.info(
            f"CRITICAL 'STUCK ACTIVE files' log confirmed for {pcap_filename} from logger '{stuck_log.name}'."
        )

        # IMMEDIATELY assert file is NOT processed (still in source_dir) because it's "stuck active"
        assert real_fs.exists(pcap_source_path), (
            "File was moved from source_dir immediately after being confirmed STUCK ACTIVE and before lost transition."
        )
        assert not real_fs.exists(env.worker_dir / pcap_filename), (
            "File unexpectedly in worker_dir while confirmed STUCK ACTIVE."
        )

        # Assert no upload attempt was made for this specific file yet
        non_expected_upload_matcher = RequestMatcher(
            uri=nifi_target_path,  # Use path from env
            method="POST",
            headers={"x-filename": pcap_filename},
        )
        env.httpserver.assert_request_made(non_expected_upload_matcher, count=0)
        test_logger.info(
            f"Confirmed no upload attempt for '{pcap_filename}' while it was 'stuck active'."
        )

        # Clear logs before the next phase to make asserting the "LOST" log cleaner and more specific
        caplog.clear()

        # 3. Transition to "Lost" Phase: File modifications have stopped.
        # Its last known mtime is 'last_simulated_mtime'.
        test_logger.info(
            f"Stopped mtime updates for {pcap_filename}. "
            f"Last actual mtime approx {last_simulated_mtime:.2f}. Waiting for 'lost' detection and processing."
        )

        # Setup NiFi server expectation for the eventual upload
        env.httpserver.expect_request(
            uri=nifi_target_path,  # Use path from env
            method="POST",
            headers={
                "x-filename": pcap_filename,
                "Content-Type": "application/octet-stream",
            },
            data=pcap_content,
        ).respond_with_data(
            f"File {pcap_filename} (stuck then lost) uploaded.", status=200
        )

        # Wait for the file to be identified as "lost" and then processed (moved and uploaded)
        # Timeout needs to cover:
        # - Scanner identifying it as no longer active.
        # - lost_timeout passing relative to its static mtime.
        # - Scanner identifying it as lost and queueing it.
        # - FileMover picking it up and moving it to worker_dir.
        # - Uploader scanning worker_dir, picking it up, and uploading it.
        processing_timeout_for_lost = (
            lost_timeout
            + (3 * scan_interval)  # Time for a few scan cycles
            + env.config.move_poll_interval_seconds
            + env.config.uploader_poll_interval_seconds
            + 5.0  # General buffer for processing and upload
        )
        test_logger.info(
            f"Waiting up to {processing_timeout_for_lost:.2f}s for file to appear in uploaded_dir."
        )

        uploaded_file_path = env.uploaded_dir / pcap_filename
        assert wait_for_file_condition_bb(
            uploaded_file_path,
            lambda p, fs_check: fs_check.exists(
                p
            ),  # Renamed fs to fs_check to avoid conflict
            real_fs,
            timeout=processing_timeout_for_lost,
        ), (
            f"File '{pcap_filename}' did not appear in uploaded_dir after becoming lost. Logs:\n{caplog.text}"
        )
        test_logger.info(f"File {pcap_filename} found in uploaded_dir.")

        # Assert "Identified file as LOST" log (INFO from process_scan_results)
        lost_log = find_log_record(
            caplog,
            logging.INFO,
            required_substrings=["Identified file as LOST", str(pcap_source_path)],
        )
        assert (
            lost_log is not None
            and lost_log.name == "datamover.scanner.process_scan_results"
        ), (
            f"Expected INFO log for 'Identified file as LOST' from 'datamover.scanner.process_scan_results' "
            f"for {pcap_source_path} not found. Logs:\n{caplog.text}"
        )
        test_logger.info(
            f"INFO 'Identified file as LOST' log confirmed for {pcap_filename}."
        )

        # 4. Final Assertions and Shutdown
        test_logger.info("Initiating application shutdown for test.")
        env.shutdown_app_event.set()
        env.app_thread.join(timeout=5.0)
        assert not env.app_thread.is_alive(), (
            "Application thread did not join successfully."
        )

        # Final file location checks
        assert not real_fs.exists(pcap_source_path), (
            "File was not removed from source_dir after processing."
        )
        assert not real_fs.exists(env.worker_dir / pcap_filename), (
            "File was not removed from worker_dir after processing."
        )

        # Verify content of the uploaded file
        with real_fs.open(uploaded_file_path, "rb") as f:
            assert f.read() == pcap_content, (
                "Content of the uploaded file does not match original."
            )

        # Verify the HTTP request was made exactly once (after it became lost and was processed)
        final_upload_matcher = RequestMatcher(
            uri=nifi_target_path,  # Use path from env
            method="POST",
            headers={
                "x-filename": pcap_filename,
                "Content-Type": "application/octet-stream",
            },
            data=pcap_content,
        )
        env.httpserver.assert_request_made(final_upload_matcher, count=1)

        test_logger.info(
            f"Test {self.test_bb_stuck_file_becomes_lost_and_processed.__name__} PASSED"
        )
