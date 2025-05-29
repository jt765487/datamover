import logging
import time

import pytest
from pytest_httpserver import RequestMatcher
from werkzeug.wrappers import Request, Response

from datamover.protocols import FS
from tests.test_utils.logging_helpers import find_log_record
from .conftest import BlackBoxTestEnv
from .helpers import (
    create_pcap_file_in_source_bb,
    append_to_app_csv_bb,
    wait_for_file_condition_bb,
)

logger = logging.getLogger(__name__)


@pytest.mark.blackbox
class TestAppUploaderResilience:
    """
    Black-Box End-to-End Tests for Data Mover Application: Uploader Resilience.

    Purpose:
    --------
    This test suite verifies the robustness of the Data Mover application's Uploader
    component, specifically its ability to handle transient issues with the remote
    NiFi endpoint by employing a retry mechanism, and to correctly process files
    once the endpoint becomes available again.

    This particular test file focuses on scenarios where the NiFi endpoint is
    temporarily unavailable or returns retryable server-side errors.

    Primary Goals for "Temporary Unavailability" Tests:
    ---------------------------------------------------
    1.  Confirm that when an upload attempt fails with a retryable error (e.g.,
        a 5xx HTTP status code from NiFi, or a simulated network timeout), the
        target .pcap file remains in the `Work Directory`.
    2.  Verify that the application logs these failed upload attempts and subsequent
        retry efforts. If backoff delays are configured to be short enough for
        testing, their effect might also be indirectly observed through log timing.
    3.  Ensure that if the NiFi endpoint becomes responsive and returns a success
        status (e.g., 2xx HTTP status code) on a subsequent retry, the Uploader
        successfully transmits the file.
    4.  Confirm that after a successful upload (post-retries), the .pcap file is
        correctly moved from the `Work Directory` to the `Uploaded Directory`.
    5.  Verify that the file is not incorrectly moved to the `Dead Letter Directory`
        when failures are transient and eventually resolve.

    Test Scope & Interactions:
    --------------------------
    -   **Input Simulation:**
        -   A .pcap file is introduced into the system such that it becomes available
          in the `Work Directory` for the `UploaderThread` to process (e.g., via
          the standard CSV trigger and subsequent move by the `FileMoverThread`).
    -   **Application Under Test (SUT):** The entire Data Mover application,
        started via its main `run(context)` function, including all relevant internal
        threads (`Tailer`, `FileMover`, `Uploader`, etc.).
    -   **Observed Outputs & Behaviors:**
        -   The location of the target .pcap file throughout the test (initially
          `Source`, then `Work` during retries, finally `Uploaded`).
        -   Application log messages detailing upload attempts, retryable errors,
          retry scheduling (if logged), and the eventual successful upload.
        -   Interactions with the `pytest-httpserver` instance (simulating NiFi):
            -   Multiple POST requests for the same file.
            -   Initial N requests receive configured 5xx error responses.
            -   A subsequent request (N+1) receives a 2xx success response.
    -   **Environment:**
        -   Real filesystem operations within temporary directories (`tmp_path`).
        -   A real application `Config` object, with `remote_host_url` pointing to
          the `pytest-httpserver`. Uploader retry parameters (`initial_backoff`,
          `max_backoff`, `request_timeout`) in the test `Config` are set to short,
          testable durations.

    Key Components & Their Test Status (Real vs. Mocked):
    ------------------------------------------------------
    * **Real Components Used:**
        -   The full application stack, with particular focus on the `UploaderThread`
          and its `RetryableFileSender` component, which uses the application's
          actual `HttpClient` implementation (e.g., `RequestsHttpClientAdapter`) to
          make real HTTP requests to the local `pytest-httpserver`.
        -   Other components like `Config`, `FS` (real OS calls), `app.run()`,
          threads for CSV processing and file moving are also active to deliver
          the file to the `Work Directory`.
    * **Test Doubles / Controlled Environment:**
        -   **HTTP Endpoint (`pytest-httpserver`):** This is critical. It's a real
          local HTTP server configured by the test to simulate NiFi's behavior,
          initially returning 5xx errors and then a 2xx success for specific requests.

    Assumptions for Test Design:
    ----------------------------
    -   The `app_test_env` fixture correctly sets up the application with a real
        filesystem interface and appropriate short timeouts/backoff periods for
        uploader retries to be observable within a practical test duration.
    -   The `RetryableFileSender` component, as described in the main system
        documentation, correctly identifies 5xx HTTP status codes and relevant
        network exceptions (like timeouts) as retryable conditions.
    -   Files in the `Work Directory` are processed by the `UploaderThread` in a
        deterministic or observable order (e.g., oldest first by modification time).
    """

    def test_bb_upload_retry_then_success_on_nifi_5xx_error(
        self,
        app_test_env: BlackBoxTestEnv,
        real_fs: FS,
        caplog: pytest.LogCaptureFixture,
    ):
        # ... (caplog, test_logger, env, nifi_target_path, pcap_filename, pcap_content, file_mtime setup) ...
        caplog.set_level(logging.DEBUG)
        test_logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}.{self.test_bb_upload_retry_then_success_on_nifi_5xx_error.__name__}"
        )
        test_logger.info("Starting test: BB_UPLOAD_RETRY_5XX_THEN_SUCCESS")

        env = app_test_env
        nifi_target_path = env.nifi_endpoint_path_str

        pcap_filename = "retry_then_success_01.pcap"
        pcap_content = b"content for retry test"
        file_mtime = time.time() - 10

        expected_headers_pattern = {
            "x-filename": pcap_filename,
            "Content-Type": "application/octet-stream",
        }
        expected_data = pcap_content

        # --- Use a handler for stateful responses ---
        # Using a list to make call_count modifiable by the inner function
        handler_call_count = [0]

        def sequenced_response_handler(
            request: Request,
        ) -> Response:  # Use werkzeug.wrappers.Request
            handler_call_count[0] += 1
            attempt_number = handler_call_count[0]

            # Optional: Add more detailed matching inside the handler if needed
            # For example, check request.data or specific headers if the URI/method isn't unique enough.
            # if request.headers.get("x-filename") != pcap_filename:
            #     return Response("Unexpected file in handler", status=400)

            test_logger.info(
                f"HTTPServer Handler: Call #{attempt_number} for {request.method} {request.path}"
            )
            if attempt_number <= 2:  # First two attempts
                test_logger.info(
                    f"HTTPServer Handler: Responding 503 for attempt #{attempt_number}"
                )
                return Response(
                    f"NiFi Service Unavailable - Attempt {attempt_number}", status=503
                )
            else:  # Third attempt onwards should succeed
                test_logger.info(
                    f"HTTPServer Handler: Responding 200 for attempt #{attempt_number}"
                )
                return Response(
                    f"File {pcap_filename} uploaded successfully on attempt {attempt_number}",
                    status=200,
                )

        # Expect any POST to this path that matches the core criteria,
        # and let the handler manage the sequence of responses.
        env.httpserver.expect_request(
            uri=nifi_target_path,
            method="POST",
            headers=expected_headers_pattern,  # Still good to match key headers
            data=expected_data,  # And data
        ).respond_with_handler(sequenced_response_handler)
        test_logger.info(
            f"HTTPServer: Configured sequenced_response_handler for POSTs to {nifi_target_path}"
        )
        # --- End of handler setup ---

        # 2. Create .pcap and signal via CSV (remains the same)
        pcap_source_path = create_pcap_file_in_source_bb(
            env.source_dir, pcap_filename, pcap_content, file_mtime, real_fs
        )
        csv_line = f"{int(file_mtime)},{str(pcap_source_path)},{'a1' * 32}"
        append_to_app_csv_bb(env.app_csv_file, csv_line, real_fs)
        test_logger.info(f"Created pcap {pcap_source_path} and signaled via CSV.")

        # 3. Wait for file to arrive in worker_dir (remains the same)
        pcap_worker_path = env.worker_dir / pcap_filename
        assert wait_for_file_condition_bb(
            pcap_worker_path,
            lambda p, fs_check: fs_check.exists(p),
            real_fs,
            timeout=10.0,
        ), f"File {pcap_filename} did not arrive in worker_dir. Logs:\n{caplog.text}"
        test_logger.info(f"File {pcap_filename} found in worker_dir.")

        # 4. Allow time for initial failed attempts and retries (remains the same)
        # This sleep needs to be long enough for at least 3 attempts to occur.
        # Attempt = uploader_poll + request_timeout + backoff
        # Your backoffs are very short (0.01s, 0.02s, 0.04s, then 0.05s).
        # Uploader poll is 0.1s. Request timeout is 2s.
        # A few seconds should be enough for 3 attempts.
        time_for_three_attempts = (
            env.config.uploader_poll_interval_seconds
            + env.config.request_timeout
            + env.config.max_backoff
        ) * 3 + 2.0  # Buffer
        test_logger.info(
            f"Waiting {time_for_three_attempts:.2f}s to allow for retries and eventual success."
        )
        # time.sleep(time_for_three_attempts) # This sleep might now be covered by wait_for_file_condition_bb below.

        # Assertions during retry phase
        # We expect at least two 503s.
        # This check can be done after the file is successfully uploaded too, by inspecting all logs.
        # For now, let's move the retry log count check after the successful upload.

        # 5. Wait for the file to eventually appear in the uploaded_dir
        pcap_uploaded_path = env.uploaded_dir / pcap_filename
        # The timeout here should be sufficient for the 3 attempts and processing.
        assert wait_for_file_condition_bb(
            pcap_uploaded_path,
            lambda p, fs_check: fs_check.exists(p),
            real_fs,
            timeout=time_for_three_attempts,  # Use the calculated time
        ), (
            f"File {pcap_filename} did not appear in uploaded_dir after retries. Logs:\n{caplog.text}"
        )
        test_logger.info(
            f"File {pcap_filename} successfully processed and found in uploaded_dir."
        )

        # Now that the main condition (file uploaded) is met, check logs
        retry_log_count = 0
        for record in caplog.records:
            if (
                record.levelno == logging.WARNING
                and "Server error during upload attempt" in record.message
                and pcap_filename in record.message
                and "(Status: 503"
                in record.message  # More specific to catch the status
                and "Retrying in" in record.message  # Ensure it's a retry message
                and record.name == "datamover.uploader.send_file_with_retries"
            ):
                retry_log_count += 1

        assert retry_log_count == 2, (
            f"Expected exactly 2 retry log messages (for 503 errors) for {pcap_filename}, found {retry_log_count}. "
            f"Logs:\n{caplog.text}"
        )
        test_logger.info(f"Confirmed exactly 2 retry log messages for {pcap_filename}.")

        # 6. Shutdown and Final Assertions (remains the same)
        test_logger.info("Initiating application shutdown for test.")
        env.shutdown_app_event.set()
        env.app_thread.join(timeout=5.0)
        assert not env.app_thread.is_alive(), "Application thread did not join."

        assert not real_fs.exists(pcap_source_path)
        assert not real_fs.exists(pcap_worker_path)

        with real_fs.open(pcap_uploaded_path, "rb") as f:
            assert f.read() == pcap_content

        # Verify HTTP server interactions:
        # The handler was called 3 times (2 for 503, 1 for 200)
        assert handler_call_count[0] == 3, (
            f"Expected the HTTPServer handler to be called 3 times, but was called {handler_call_count[0]} times."
        )
        # We can also use assert_request_made with the original matcher to ensure
        # 3 requests matching that overall pattern were made.
        final_upload_matcher = RequestMatcher(
            uri=nifi_target_path,
            method="POST",
            headers=expected_headers_pattern,
            data=expected_data,
        )
        env.httpserver.assert_request_made(final_upload_matcher, count=3)
        test_logger.info(
            "NiFi server interaction count (3 attempts via handler) confirmed."
        )

        success_log = find_log_record(
            caplog,
            logging.INFO,
            required_substrings=["Upload SUCCESS", pcap_filename, "Status: 200"],
        )
        assert (
            success_log is not None
            and success_log.name == "datamover.uploader.send_file_with_retries"
        ), (
            f"Expected 'Upload SUCCESS' log for {pcap_filename} not found. Logs:\n{caplog.text}"
        )
        test_logger.info(f"Upload success log confirmed for {pcap_filename}.")

        test_logger.info(
            f"Test {self.test_bb_upload_retry_then_success_on_nifi_5xx_error.__name__} PASSED"
        )
