"""
Black-Box End-to-End Integration Tests for the Data Mover Application: CSV Happy Path.

Purpose:
--------
This test file verifies the successful end-to-end processing pipeline for .pcap files
that are correctly logged via the application's CSV mechanism. It simulates the
external application creating a .pcap file and its corresponding CSV log entry,
then observes the Data Mover application's response.

The primary goal is to confirm that .pcap files identified through CSV processing
are successfully uploaded to the remote HTTP endpoint and moved to the `uploaded_dir`.

Test Scope & Interactions:
--------------------------
-   **Input Simulation:**
    -   Creation of .pcap files in a designated `source_dir`.
    -   Appending valid lines to a CSV log file in a `csv_dir`.
-   **Application Under Test (SUT):** The entire Data Mover application, started
    via its main `run(context)` function. This includes all its internal threads.
-   **Observed Outputs & Behaviors:**
    -   Final location of .pcap files (in `uploaded_dir`).
    -   Absence of processed files in `source_dir` and `worker_dir`.
    -   Calls made to the `pytest-httpserver` instance (simulating the remote
        HTTP endpoint), including verification of request URI, method, headers, and call count.
-   **Environment:**
    -   Real filesystem operations within temporary directories (`tmp_path`).
    -   Real application `Config` objects, with `remote_url` pointing to the
        `pytest-httpserver` instance.
    -   Real time (`time.sleep`, etc.) for operational delays and timeouts.

Key Components & Their Test Status (Real vs. Mocked):
------------------------------------------------------
*   **Real Components Used:**
    -   Almost all application components, including `Config`, `FS` (real OS calls),
        `datamover.app.run()`, all thread factories, core processing threads
        (Scanner, FileMover, Uploader, Tailer), `RetryableFileSender` (using its
        real `HttpClient` adapter like `RequestsHttpClientAdapter`),
        `scan_directory_and_filter`, `move_file_safely_impl`, `parse_log_line`,
        `flush_buffer`, and Python concurrency primitives.
    -   The application's *actual* HTTP client implementation (e.g., `RequestsHttpClientAdapter`)
        will be making *real* HTTP requests to the local `pytest-httpserver`.

*   **Test Doubles / Controlled Environment:**
    -   **HTTP Endpoint (`pytest-httpserver`):** An actual HTTP server is started locally
        on a free port by `pytest-httpserver`. Tests configure this server to expect
        specific requests and provide defined responses (200 OK, 4xx, 5xx, etc.).
        This replaces direct mocking of the `HttpClient` protocol instance.

Assumptions for Test Design:
----------------------------
-   The application's `build_context` function correctly instantiates and uses the
    `HttpClient` implementation (e.g., `RequestsHttpClientAdapter`) that will
    target the `remote_url` specified in the `Config`.
-   Other assumptions from the main specification document apply.

This approach provides a high degree of confidence by testing the application's
full stack, including its actual HTTP client code interacting with a real, albeit
test-controlled, HTTP server.
"""

import logging
import time

import pytest
from pytest_httpserver import RequestMatcher

from datamover.file_functions.fs_mock import FS
from .conftest import BlackBoxTestEnv
from .helpers import (
    create_pcap_file_in_source_bb,
    append_to_app_csv_bb,
    wait_for_file_condition_bb,
)

logger = logging.getLogger(__name__)
DUMMY_VALID_HASH = "a1" * 32
NIFI_ENDPOINT_PATH = (
    "/nifi_data_upload_endpoint"  # Must match what's in conftest's Config
)


@pytest.mark.blackbox
class TestAppCsvHappyPath:
    def test_bb_successful_pcap_via_csv_processing_httpserver(
        self,
        app_test_env: BlackBoxTestEnv,
        real_fs: FS,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)
        test_logger = logging.getLogger(
            f"{__name__}.{self.test_bb_successful_pcap_via_csv_processing_httpserver.__name__}"
        )
        test_logger.info("Starting BB_CSV_SUCCESS_SINGLE (HTTPServer)")

        env = app_test_env
        filename = "test_pcap_01_hs.pcap"
        content = b"dummy pcap content for httpserver test01"
        mtime = time.time() - 10

        # 1) Tell pytest-httpserver exactly what to expect (uri, method, headers, raw bytes)
        env.httpserver.expect_request(
            uri=NIFI_ENDPOINT_PATH,
            method="POST",
            headers={
                "x-filename": filename,
                "Content-Type": "application/octet-stream",
            },
            data=content,
        ).respond_with_data("Upload OK via pytest-httpserver", status=200)

        # 2) Drop the .pcap and corresponding CSV line
        pcap_path = create_pcap_file_in_source_bb(
            env.source_dir, filename, content, mtime, real_fs
        )
        csv_line = f"{int(mtime)},{pcap_path},{DUMMY_VALID_HASH}"
        append_to_app_csv_bb(env.app_csv_file, csv_line, real_fs)

        # 3) Wait until it moves into uploaded_dir
        uploaded = env.uploaded_dir / filename
        assert wait_for_file_condition_bb(
            uploaded, lambda p, fs: fs.exists(p), real_fs, timeout=10
        ), f"File never appeared; logs:\n{caplog.text}"

        # 4) Shut down the app
        env.shutdown_app_event.set()
        env.app_thread.join(timeout=2.0)
        assert not env.app_thread.is_alive()

        # 5) Verify file contents & cleanup
        assert not real_fs.exists(pcap_path)
        assert not real_fs.exists(env.worker_dir / filename)
        with real_fs.open(uploaded, "rb") as f:
            assert f.read() == content

        # 6) (Optional) Explicitly assert the POST was made exactly once
        matcher = RequestMatcher(
            NIFI_ENDPOINT_PATH,
            method="POST",
            headers={
                "x-filename": filename,
                "Content-Type": "application/octet-stream",
            },
            data=content,
        )
        env.httpserver.assert_request_made(matcher, count=1)

        test_logger.info("Test BB_CSV_SUCCESS_SINGLE (HTTPServer) PASSED")
