import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pytest
from pytest_httpserver import HTTPServer

from datamover.app import run as run_application
from datamover.protocols import FS, HttpClient, FileScanner
from datamover.startup_code.context import build_context
from datamover.startup_code.load_config import Config

logger = logging.getLogger(__name__)


# This AppContext is just for type hinting within this conftest if needed,
# the actual app uses the one from startup_code.
@dataclass
class AppContext:
    config: Config
    shutdown_event: threading.Event
    fs: FS
    http_client: HttpClient
    file_scanner: FileScanner


class BlackBoxTestEnv(NamedTuple):
    config: Config
    source_dir: Path
    worker_dir: Path
    uploaded_dir: Path
    dead_letter_dir: Path
    csv_dir: Path
    app_csv_file: Path
    httpserver: HTTPServer
    nifi_endpoint_path_str: str  # <<< ADDED: To store the NIFI endpoint path string
    shutdown_app_event: threading.Event
    app_thread: threading.Thread


@pytest.fixture(scope="function")
def app_test_env(
    tmp_path: Path,
    real_fs: FS,
    httpserver: HTTPServer,
) -> BlackBoxTestEnv:
    # 1. Create Directories
    base_dir = tmp_path / "bb_app_root_live_hs"
    logger_dir_for_test = base_dir / "test_logs_bb"
    source_dir = base_dir / "source_files"
    worker_dir = base_dir / "worker_files"
    uploaded_dir = base_dir / "uploaded_files"
    dead_letter_dir = base_dir / "dead_letter_files"
    csv_dir = base_dir / "csv_logs"
    app_csv_file_path = csv_dir / "app_events.test.csv"

    for d_path_item in [
        logger_dir_for_test,
        source_dir,
        worker_dir,
        uploaded_dir,
        dead_letter_dir,
        csv_dir,
    ]:
        real_fs.mkdir(d_path_item, parents=True, exist_ok=True)

    with real_fs.open(app_csv_file_path, "w", encoding="utf-8") as f:
        f.write("")

    # 2. Create Test-Specific Config, using httpserver's URL
    nifi_endpoint_path_str = "/nifi_data_upload_endpoint"  # Define the path string here
    test_config = Config(
        base_dir=base_dir,
        logger_dir=logger_dir_for_test,
        source_dir=source_dir,
        worker_dir=worker_dir,
        uploaded_dir=uploaded_dir,
        dead_letter_dir=dead_letter_dir,
        csv_dir=csv_dir,
        pcap_extension_no_dot="pcap",
        csv_extension_no_dot="csv",
        move_poll_interval_seconds=0.1,
        scanner_check_seconds=0.2,  # Ensure this matches your Config class attribute name
        lost_timeout_seconds=0.3,
        stuck_active_file_timeout_seconds=0.5,
        event_queue_poll_timeout_seconds=0.1,
        uploader_poll_interval_seconds=0.1,
        heartbeat_target_interval_s=60.0,
        remote_host_url=httpserver.url_for(
            nifi_endpoint_path_str
        ),  # Use the path string here
        request_timeout=2.0,
        verify_ssl=False,
        initial_backoff=0.01,
        max_backoff=0.05,
    )

    # 3. Prepare AppContext
    app_context_obj = build_context(config=test_config, fs_override=real_fs)
    app_shutdown_event = app_context_obj.shutdown_event

    # 4. Start Application in a Thread
    app_run_thread = threading.Thread(
        target=run_application,
        args=(app_context_obj,),
        name="BlackBoxAppThreadHS",
        daemon=True,
    )
    app_run_thread.start()
    logger.info("BlackBoxAppThread (with HTTPServer) started for test.")
    time.sleep(0.8)  # Allow some time for the app to initialize

    yield BlackBoxTestEnv(
        config=test_config,
        source_dir=source_dir,
        worker_dir=worker_dir,
        uploaded_dir=uploaded_dir,
        dead_letter_dir=dead_letter_dir,
        csv_dir=csv_dir,
        app_csv_file=app_csv_file_path,
        httpserver=httpserver,
        nifi_endpoint_path_str=nifi_endpoint_path_str,  # <<< ADDED: Yield the path string
        shutdown_app_event=app_shutdown_event,
        app_thread=app_run_thread,
    )

    # 5. Teardown
    logger.info("Initiating teardown for black-box app environment (HTTPServer)...")
    if not app_shutdown_event.is_set():
        app_shutdown_event.set()
    app_run_thread.join(timeout=5.0)
    if app_run_thread.is_alive():  # pragma: no cover
        logger.error("BBAppThread (HTTPServer) DID NOT JOIN!")
    else:
        logger.info("BBAppThread (HTTPServer) joined successfully.")
    logger.info("Black-box app env (HTTPServer) teardown complete.")
