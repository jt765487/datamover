import logging
import threading
from pathlib import Path

from datamover.file_functions.fs_mock import FS
from datamover.protocols import FileScanner

from datamover.uploader.send_file_with_retries import RetryableFileSender

logger = logging.getLogger(__name__)


class UploaderThread(threading.Thread):
    """
    Background thread that scans a directory for files with a given extension and
    uploads them using a retryable sender. Implements a heartbeat and suppresses
    excessive empty-scan debug logs by batching them into streak reports.
    """

    def __init__(
        self,
        *,
        thread_name: str,
        validated_work_dir: Path,
        file_extension_no_dot: str,
        stop_event: threading.Event,
        poll_interval: float,
        heartbeat_interval: float,
        file_scanner: FileScanner,
        file_sender: RetryableFileSender,
        fs: FS,
    ):
        """
        Initialize the uploader thread.

        Args:
            thread_name: Name for the thread (used in logs).
            validated_work_dir: Directory to scan for files.
            file_extension_no_dot: File extension to watch (without leading dot).
            stop_event: Event to signal thread shutdown.
            poll_interval: Seconds between scan cycles.
            heartbeat_interval: Seconds between heartbeat logs.
            file_scanner: Callable to list files in the directory.
            file_sender: Retryable sender for uploading files.
            fs: Filesystem abstraction.
        """
        super().__init__(daemon=True, name=thread_name)

        # Configuration parameters
        self.validated_work_dir = validated_work_dir
        self.file_extension_no_dot = file_extension_no_dot
        self.stop_event = stop_event
        self.poll_interval = poll_interval
        self.file_scanner = file_scanner
        self.file_sender = file_sender
        self.fs = fs

        # Track files that failed critically (no further retries)
        self.critically_failed_files: set[Path] = set()

        # Setup heartbeat: number of cycles per heartbeat log
        self.heartbeat_target_interval_s: float = heartbeat_interval
        self.cycles_for_heartbeat: int = max(
            1,
            int(round(self.heartbeat_target_interval_s / self.poll_interval)),
        )

        # Count consecutive empty scans to reduce log noise
        self.empty_scan_streak: int = 0

        # Internal counters
        self.current_cycle_count: int = 0
        self.scan_cycles_completed: int = 0
        self.files_processed_count: int = 0

        logger.debug(
            "%s initialized. Watching %s for *.%s. Heartbeat every %d cycles (~%s s).",
            self.name,
            self.validated_work_dir,
            self.file_extension_no_dot,
            self.cycles_for_heartbeat,
            self.heartbeat_target_interval_s,
        )

    def run(self) -> None:
        """
        Main loop: periodically scan for files, upload them, and handle stop signals.
        Logs a heartbeat at the configured interval and summarizes empty scans in batches.
        """
        logger.info("%s starting run loop.", self.name)

        while not self.stop_event.is_set():
            self.current_cycle_count += 1

            # Emit heartbeat when enough cycles have passed
            if self.current_cycle_count >= self.cycles_for_heartbeat:
                logger.info(
                    "%s heartbeat: watching directory %s",
                    self.name,
                    self.validated_work_dir,
                )
                self.current_cycle_count = 0

            try:
                # Scan for files matching the configured extension
                entries = self.file_scanner(
                    directory=self.validated_work_dir,
                    fs=self.fs,
                    extension_no_dot=self.file_extension_no_dot,
                )

                if not entries:
                    # No files found: increment streak and log sparsely
                    self.empty_scan_streak += 1
                    if self.empty_scan_streak == 1 or (
                        self.empty_scan_streak % self.cycles_for_heartbeat == 0
                    ):
                        logger.debug(
                            "%s: no files found for %d consecutive cycle(s).",
                            self.name,
                            self.empty_scan_streak,
                        )
                else:
                    # Files appeared after emptiness: log recovery and reset
                    if self.empty_scan_streak > 0:
                        logger.debug(
                            "%s: files detected after %d empty cycle(s).",
                            self.name,
                            self.empty_scan_streak,
                        )
                    self.empty_scan_streak = 0

                # Process each found file
                for entry in entries:
                    # Re-check stop event between files
                    if self.stop_event.is_set():
                        logger.info(
                            "%s stop event detected; breaking file loop.",
                            self.name,
                        )
                        break

                    path = entry.path
                    # Skip files that have permanently failed
                    if path in self.critically_failed_files:
                        logger.debug(
                            "%s skipping critically failed file: %s",
                            self.name,
                            path,
                        )
                        continue

                    logger.debug("%s sending file: %s", self.name, path)
                    try:
                        ok = self.file_sender.send_file(path)
                        if ok:
                            self.files_processed_count += 1
                        else:
                            # Sender returned False: mark file as permanently failed
                            self.critically_failed_files.add(path)
                            logger.error(
                                "%s critical failure for file %s (sender returned False).",
                                self.name,
                                path,
                            )
                    except Exception:
                        # Unexpected exception: log and mark as critically failed
                        self.critically_failed_files.add(path)
                        logger.exception(
                            "%s CRITICAL: exception during send_file('%s').",
                            self.name,
                            path,
                        )

                # One full scan cycle completed
                self.scan_cycles_completed += 1

            except Exception:
                # Catch-all to prevent thread from dying on unexpected errors
                logger.exception(
                    "%s unexpected error in scan/process loop.",
                    self.name,
                )

            # Wait for next cycle or stop signal
            if not self.stop_event.is_set():
                if self.stop_event.wait(self.poll_interval):
                    logger.info(
                        "%s received stop signal during wait; exiting.",
                        self.name,
                    )
                    break

        logger.info("%s stopping run loop.", self.name)
