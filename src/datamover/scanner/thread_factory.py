import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from typing import Optional

from datamover.file_functions.directory_validation import (
    resolve_and_validate_directory,
)
from datamover.file_functions.fs_mock import FS
from datamover.protocols import SleepCallable
from datamover.scanner.do_single_cycle import DoSingleCycle
from datamover.scanner.scan_thread import ScanThread

logger = logging.getLogger(__name__)


def create_scan_thread(
    *,
    scan_directory_path: Path,
    file_extension_to_scan: str,
    scan_interval_seconds: float,
    lost_timeout_seconds: float,
    stuck_active_file_timeout_seconds: float,
    lost_file_queue: Queue[Path],
    stop_event: threading.Event,
    fs: FS,
    time_func: Callable[[], float] = time.time,
    monotonic_func: Callable[[], float] = time.monotonic,
    sleep_func: Optional[SleepCallable] = None,
) -> ScanThread:
    """
    Factory function to create and configure a ScanThread for directory scanning.

    - Validates the scan_directory_path using the provided fs.
    - Constructs a DoSingleCycle processor with validated paths and injected dependencies.
    - Returns a configured ScanThread.

    Args:
        scan_directory_path: The root directory to scan.
        file_extension_to_scan: The file extension (without dot) to look for.
        scan_interval_seconds: How often the scanning cycle should run.
        lost_timeout_seconds: Duration after which a found file is considered "lost".
        stuck_active_file_timeout_seconds: Duration after which an active file is
                                           considered "stuck".
        lost_file_queue: Queue for enqueuing newly lost file Paths.
        stop_event: Event to signal the thread to stop scanning.
        fs: Filesystem abstraction instance.
        time_func: Function returning current wall-clock time.
        monotonic_func: Function returning current monotonic time.
        sleep_func: Optional sleep function for the ScanThread; defaults to time.sleep.

    Returns:
        A configured but not started ScanThread instance.

    Raises:
        FileNotFoundError, NotADirectoryError, ValueError: If directory validation fails.
        (The check for scan_interval_seconds <= 0 is assumed to be handled by ScanThread or elsewhere)
    """
    # 1. Resolve and validate configured directory using the direct argument
    validated_scan_directory: Path = resolve_and_validate_directory(
        raw_path=scan_directory_path,
        fs=fs,
        dir_label="scan source directory",
    )

    # 2. Create the single-cycle processor
    processor = DoSingleCycle(
        validated_directory_to_scan=validated_scan_directory,
        extension_to_scan_no_dot=file_extension_to_scan,
        lost_timeout=lost_timeout_seconds,
        stuck_active_file_timeout=stuck_active_file_timeout_seconds,
        lost_file_queue=lost_file_queue,
        time_func=time_func,
        monotonic_func=monotonic_func,
        fs=fs,
    )

    # 3. Choose sleep function (Step 5 in original code)
    actual_sleep_func = time.sleep if sleep_func is None else sleep_func

    # 4. Construct the scanning thread (Step 6 in original code)
    thread_name = f"Scanner-{validated_scan_directory.name}"
    scan_thread = ScanThread(
        processor=processor,
        stop_event=stop_event,
        scan_interval_seconds=scan_interval_seconds,
        sleep_func=actual_sleep_func,
        monotonic_func=monotonic_func,
        name=thread_name,
    )

    return scan_thread
