import logging
import time
from pathlib import Path
from typing import Callable, Dict
from unittest.mock import MagicMock

from datamover.file_functions.fs_mock import FS
from datamover.protocols import HttpResponse
from tests.test_utils.fs_helpers import create_and_stamp_real_fs

logger = logging.getLogger(__name__)


def create_simulated_http_response_bb(
    status_code: int, text: str = "", headers: Dict = None
) -> MagicMock:
    """Helper to create a mock HttpResponse object for black-box tests."""
    response = MagicMock(spec=HttpResponse)
    response.status_code = status_code
    response.text = text
    response.headers = headers if headers is not None else {}
    return response


def create_pcap_file_in_source_bb(
    source_dir: Path,
    filename: str,
    content: bytes,
    mtime_to_set: float,
    real_fs_for_create: FS,
) -> Path:
    """Creates a pcap file in the source directory with specific content and mtime."""
    file_path = source_dir / filename
    create_and_stamp_real_fs(
        real_fs_for_create, file_path, len(content), mtime_to_set, initial_create=True
    )
    with real_fs_for_create.open(file_path, "wb") as f:
        f.write(content)
    logger.debug(f"BB Test Helper: Created pcap {file_path} with mtime {mtime_to_set}")
    return file_path


def append_to_app_csv_bb(
    csv_file_path: Path, line_content: str, real_fs_for_append: FS
):
    """Appends a line to the specified CSV file."""
    with real_fs_for_append.open(csv_file_path, "a", encoding="utf-8") as f:
        f.write(line_content + "\n")
    logger.debug(f"BB Test Helper: Appended to CSV {csv_file_path}: {line_content}")


def wait_for_file_condition_bb(
    file_path: Path,
    condition_met: Callable[[Path, FS], bool],
    real_fs_check: FS,
    timeout: float,
    poll_interval: float = 0.1,
) -> bool:
    """Waits for a condition on a file to be true (e.g., exists, not exists)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition_met(file_path, real_fs_check):
            return True
        time.sleep(poll_interval)
    logger.warning(f"BB Test Helper: Timeout waiting for condition on {file_path}")
    return False
