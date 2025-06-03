# datamover/purger/thread_factory.py
import logging
import threading
from pathlib import Path
from typing import Optional

from datamover.file_functions.fs_mock import FS
from datamover.purger.purger_thread import PurgerThread  # Import the new PurgerThread

logger = logging.getLogger(__name__)


def create_purger_thread(
    *,
    work_dir_path: Path,
    uploaded_dir_path: Path,
    fs: FS,
    total_disk_capacity_bytes: int,
    target_disk_usage_percent: float,
    check_interval_seconds: float,
    stop_event: threading.Event,
    thread_name: Optional[str] = "PurgerThread",
) -> PurgerThread:
    """
    Constructs a PurgerThread that periodically calls manage_disk_space.

    Args:
        work_dir_path: Path to the directory where new files are staged (e.g., config.worker_dir).
        uploaded_dir_path: Path to the directory where uploaded files are moved (e.g., config.uploaded_dir).
        fs: Filesystem abstraction instance.
        total_disk_capacity_bytes: Total capacity of the disk being monitored, in bytes.
        target_disk_usage_percent: The target disk usage (e.g., 0.80 for 80%).
        check_interval_seconds: How often the purger thread should run its check.
        stop_event: Shared threading.Event to signal thread shutdown.
        thread_name: Optional name for the thread.

    Returns:
        A configured PurgerThread instance (daemon, not yet started).
    """
    # Basic validation (can be expanded if necessary)
    if not isinstance(work_dir_path, Path) or not isinstance(uploaded_dir_path, Path):
        raise TypeError("work_dir_path and uploaded_dir_path must be Path objects.")
    if not isinstance(fs, FS):
        raise TypeError("fs must be an FS instance.")
    if total_disk_capacity_bytes < 0:
        raise ValueError("total_disk_capacity_bytes cannot be negative.")
    if not (0.0 < target_disk_usage_percent <= 1.0):
        raise ValueError(
            "target_disk_usage_percent must be between 0.0 (exclusive) and 1.0 (inclusive)."
        )

    logger.info(
        "Creating %s: Configured for WorkDir='%s', UploadedDir='%s'. Target usage < %.0f%% of %s bytes. CheckInterval=%.1fs.",
        thread_name,
        work_dir_path,
        uploaded_dir_path,
        target_disk_usage_percent * 100,
        f"{total_disk_capacity_bytes:,}",
        check_interval_seconds,
    )

    thread = PurgerThread(
        work_dir_path=work_dir_path,
        uploaded_dir_path=uploaded_dir_path,
        fs=fs,
        total_disk_capacity_bytes=total_disk_capacity_bytes,
        target_disk_usage_percent=target_disk_usage_percent,
        check_interval_seconds=check_interval_seconds,
        stop_event=stop_event,
        name=thread_name,
    )
    return thread
