import logging
import threading
from pathlib import Path
from typing import Optional

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.get_effective_disk_capacity import get_disk_capacity_for_path
from datamover.purger.purger_thread import PurgerThread

logger = logging.getLogger(__name__)


def create_purger_thread(
        *,
        work_dir_path: Path,
        uploaded_dir_path: Path,  # Used for capacity detection if configured_capacity is 0
        fs: FS,
        total_disk_capacity_bytes: int,
        target_disk_usage_percent: float,
        check_interval_seconds: float,
        stop_event: threading.Event,
        thread_name: Optional[str] = "PurgerThread",
) -> PurgerThread:
    """
    Constructs a PurgerThread.
    If configured_total_disk_capacity_bytes is 0, capacity is auto-detected
    using 'uploaded_dir_path'.

    Raises:
        ValueError: For invalid configuration parameters not caught by Config loading.
        DiskCapacityError: If auto-detection of disk capacity fails (propagated from
                           get_disk_capacity_for_path). This will typically lead to
                           an AppSetupError in the main app.
    """
    final_total_disk_capacity_bytes: int

    if total_disk_capacity_bytes == 0:
        logger.info(
            "Configured total_disk_capacity_bytes is 0. Attempting auto-detection using path: %s",
            uploaded_dir_path,
        )
        final_total_disk_capacity_bytes = get_disk_capacity_for_path(uploaded_dir_path)
    elif total_disk_capacity_bytes > 0:
        final_total_disk_capacity_bytes = total_disk_capacity_bytes
    else:
        # Should be caught by Config validation, but safeguard.
        raise ValueError(
            f"Invalid configured_total_disk_capacity_bytes: {total_disk_capacity_bytes}. Must be >= 0."
        )

    logger.info(
        "Creating %s: WorkDir='%s', UploadedDir='%s'. Target usage < %.0f%% of %s bytes. CheckInterval=%.1fs.",
        thread_name,
        work_dir_path,
        uploaded_dir_path,
        target_disk_usage_percent * 100,
        f"{final_total_disk_capacity_bytes:,}",
        check_interval_seconds,
    )

    thread = PurgerThread(
        work_dir_path=work_dir_path,
        uploaded_dir_path=uploaded_dir_path,
        fs=fs,
        total_disk_capacity_bytes=final_total_disk_capacity_bytes,
        target_disk_usage_percent=target_disk_usage_percent,
        check_interval_seconds=check_interval_seconds,
        stop_event=stop_event,
        name=thread_name,
    )
    return thread
