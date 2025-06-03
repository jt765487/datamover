import logging
import threading
from pathlib import Path
from typing import Optional

from datamover.file_functions.fs_mock import FS
from datamover.purger.manage_disk_space import manage_disk_space

logger = logging.getLogger(__name__)


class PurgerThread(threading.Thread):
    def __init__(
        self,
        *,
        work_dir_path: Path,
        uploaded_dir_path: Path,
        fs: FS,
        total_disk_capacity_bytes: int,
        target_disk_usage_percent: float,
        check_interval_seconds: float,
        stop_event: threading.Event,
        name: Optional[str] = "PurgerThread",
    ):
        super().__init__(daemon=True, name=name)
        self.work_dir_path = work_dir_path
        self.uploaded_dir_path = uploaded_dir_path
        self.fs = fs
        self.total_disk_capacity_bytes = total_disk_capacity_bytes
        self.target_disk_usage_percent = target_disk_usage_percent
        self.check_interval_seconds = check_interval_seconds
        self.stop_event = stop_event
        self.cycles_completed = 0

    def run(self) -> None:
        logger.info(
            "%s starting. Monitoring WorkDir: '%s', UploadedDir: '%s'. "
            "Target usage: < %.0f%% of %s bytes. Check Interval: %.1fs.",
            self.name,
            self.work_dir_path,
            self.uploaded_dir_path,
            self.target_disk_usage_percent * 100,
            f"{self.total_disk_capacity_bytes:,}",
            self.check_interval_seconds,
        )

        while not self.stop_event.is_set():
            try:
                logger.debug(
                    "%s: Starting disk space management cycle #%d.",
                    self.name,
                    self.cycles_completed + 1,
                )
                manage_disk_space(
                    work_dir_path=self.work_dir_path,
                    uploaded_dir_path=self.uploaded_dir_path,
                    fs=self.fs,
                    total_disk_capacity_bytes=self.total_disk_capacity_bytes,
                    target_disk_usage_percent=self.target_disk_usage_percent,
                )
                self.cycles_completed += 1
                logger.debug(
                    "%s: Disk space management cycle #%d finished.",
                    self.name,
                    self.cycles_completed,
                )

            except Exception as e:
                logger.exception(
                    "%s: Unhandled error during disk space management cycle: %s",
                    self.name,
                    e,
                )
                if not self.stop_event.is_set():
                    self.stop_event.wait(timeout=min(self.check_interval_seconds / 2, 5.0)) # Shorter for error recovery

            if (
                self.stop_event.is_set()
            ):  # Check after the potentially long manage_disk_space call
                break

            # Wait for the next check interval or until stop_event is set
            interrupted = self.stop_event.wait(timeout=self.check_interval_seconds)
            if interrupted:
                logger.info(
                    "%s: Stop event received during wait, exiting loop.", self.name
                )
                break

        logger.info(
            "%s stopping. Total cycles completed: %d.", self.name, self.cycles_completed
        )

    def stop(self) -> None:
        """Signals the thread to stop its execution loop."""
        if not self.stop_event.is_set():
            logger.info("%s: Stop requested", self.name)
            self.stop_event.set()
        else:
            logger.debug("%s: Stop already requested", self.name)
