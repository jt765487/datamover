import logging
from pathlib import Path
from queue import Queue
from typing import Callable, Dict, Set, Tuple, List, Optional

from datamover.file_functions.file_exceptions import ScanDirectoryError

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.file_functions.scan_directory_and_filter import (
    scan_directory_and_filter,
)
from datamover.queues.queue_functions import safe_put, QueuePutError

from datamover.scanner.process_scan_results import process_scan_results
from datamover.scanner.scan_reporting import report_state_changes
from datamover.scanner.file_state_record import FileStateRecord

logger = logging.getLogger(__name__)


def _get_app_name_from_path(file_path: Path) -> Optional[str]:
    """
    Extracts the app name from a filename like 'APPNAME-timestamp.ext'.
    The app name is assumed to be the part of the filename before the first hyphen.
    """
    name = file_path.name
    head, sep, _ = name.partition('-')
    if head and sep:
        return head

    # If there's no hyphen (or it starts with one), warn and return None
    logger.warning(
        "Could not extract app name (part before first hyphen) from filename: %r",
        name,
    )
    return None

class DoSingleCycle:
    """
    Encapsulates the logic for performing a single directory scan cycle.

    Scans the validated directory for files matching a specific extension.
    It processes scan results to update file states, identify 'lost' files
    (stale and not updated), and 'stuck active' files (active but present too long).
    'Lost' files are reported and queued. 'Stuck active' files are reported.
    It relies on injected dependencies for FS operations, time, configuration, and queuing.
    """

    def __init__(
        self,
        *,
        validated_directory_to_scan: Path,
        csv_restart_directory: Path,
        extension_to_scan_no_dot: str,
        lost_timeout: float,
        stuck_active_file_timeout: float,
        lost_file_queue: Queue[Path],  # Changed back from output_queue
        time_func: Callable[[], float],
        monotonic_func: Callable[[], float],
        fs: FS,
    ):
        """
        Initializes the processor with its dependencies and configuration.

        Args:
            validated_directory_to_scan: Validated Path of the directory to scan.
            csv_restart_directory: Validated Path of the directory for .restart files.
            extension_to_scan_no_dot: File extension to filter by (e.g., "pcap").
            lost_timeout: Duration (seconds) after which an unmodified file is 'lost'.
            stuck_active_file_timeout: Duration (seconds) after being first seen,
                                       beyond which an *active* file is 'stuck active'.
            lost_file_queue: Queue for enqueuing paths of 'lost' files.
            time_func: Callable returning current wall-clock time (e.g., `time.time()`).
            monotonic_func: Callable returning current monotonic time (e.g., `time.monotonic()`).
            fs: Filesystem abstraction instance.
        """
        self.extension_no_dot: str = extension_to_scan_no_dot
        self.csv_restart_directory: Path = csv_restart_directory
        self.lost_timeout: float = lost_timeout
        self.stuck_active_file_timeout: float = stuck_active_file_timeout
        self.lost_file_queue: Queue[Path] = lost_file_queue  # Changed back
        self.time_func: Callable[[], float] = time_func
        self.monotonic_func: Callable[[], float] = monotonic_func
        self.fs: FS = fs
        self.directory_to_scan: Path = validated_directory_to_scan
        self.lost_queue_name = (
            f"LostFileQ-{self.directory_to_scan.name}"  # Changed back
        )

        logger.info(
            "Initialized %s for '%s' [CSV Restart Dir: '%s', Ext: '.%s', Lost Timeout: %.1fs, Stuck Active Timeout: %.1fs]",
            self.__class__.__name__,
            self.directory_to_scan,
            self.csv_restart_directory,
            self.extension_no_dot,
            self.lost_timeout,
            self.stuck_active_file_timeout,
        )

    def process_one_cycle(
        self,
        current_file_states: Dict[Path, FileStateRecord],
        previously_lost_paths: Set[Path],
        previously_stuck_active_paths: Set[Path],
    ) -> Tuple[Dict[Path, FileStateRecord], Set[Path], Set[Path]]:
        """
        Executes one full scan cycle.

        Args:
            current_file_states: The state of all monitored files from the previous cycle.
            previously_lost_paths: Set of paths considered 'lost' in the previous cycle.
            previously_stuck_active_paths: Set of paths considered 'stuck active'
                                           in the previous cycle.
        Returns:
            A tuple containing:
            - next_file_states: The calculated state of all monitored files for the next cycle.
            - currently_lost_paths: Paths identified as 'lost' in *this* cycle.
            - currently_stuck_active_paths: Paths identified as 'stuck active' in *this* cycle.

        Raises:
            ScanDirectoryError: If the underlying directory scan fails critically.
        """
        logger.debug("Processor starting cycle for '%s'", self.directory_to_scan)

        # --- Phase 1: Scan & Filter ---
        try:
            gathered_data: List[GatheredEntryData] = scan_directory_and_filter(
                directory=self.directory_to_scan,
                fs=self.fs,
                extension_no_dot=self.extension_no_dot,
            )
            # This is a high-volume, keep at DEBUG
            logger.debug(
                "Scan found %d files matching '.%s' in '%s'",
                len(gathered_data),
                self.extension_no_dot,
                self.directory_to_scan,
            )
        except ScanDirectoryError:
            logger.error(
                "ScanDirectoryError during scan for '%s'. Re-raising.",
                self.directory_to_scan,
            )
            raise
        except (
            Exception
        ) as e:
            logger.exception(
                "Unexpected error during scan_directory_and_filter for '%s'. Wrapping in ScanDirectoryError.",
                self.directory_to_scan,
            )
            raise ScanDirectoryError(
                directory=self.directory_to_scan,
                message="Unexpected error during scan or filter",
                original_exception=e,
            ) from e

        # --- Phase 2: Process Scan Results ---
        try:
            mono_now: float = self.monotonic_func()
            wall_now: float = self.time_func()
            (
                next_file_states,
                removed_tracking_paths,
                currently_lost_paths,
                currently_stuck_active_paths,
            ) = process_scan_results(
                gathered_data=gathered_data,
                existing_states=current_file_states,
                lost_timeout=self.lost_timeout,
                stuck_active_timeout=self.stuck_active_file_timeout,
                monotonic_now=mono_now,
                wall_now=wall_now,
            )
            # High volume, keep at DEBUG
            logger.debug(
                "Processor results for '%s': %d next states, %d removed, %d lost, %d stuck active.",
                self.directory_to_scan,
                len(next_file_states),
                len(removed_tracking_paths),
                len(currently_lost_paths),
                len(currently_stuck_active_paths),
            )
        except Exception:  # Error in core logic, log as EXCEPTION
            logger.exception(
                "Processor error during process_scan_results for '%s'. Returning current states.",
                self.directory_to_scan,
            )
            return (
                current_file_states,
                previously_lost_paths,
                previously_stuck_active_paths,
            )

        # --- Phase 3a: Calculate Deltas ---
        try:
            newly_lost_paths = currently_lost_paths - previously_lost_paths
            newly_stuck_active_paths = (
                currently_stuck_active_paths - previously_stuck_active_paths
            )
            # High volume, keep at DEBUG
            logger.debug(
                "Processor deltas for '%s': %d newly lost, %d newly stuck active.",
                self.directory_to_scan,
                len(newly_lost_paths),
                len(newly_stuck_active_paths),
            )
        except Exception:  # Error in simple calculation, log as EXCEPTION
            logger.exception(
                "Processor error calculating problem file deltas for '%s'. Returning current states.",
                self.directory_to_scan,
            )
            return (
                current_file_states,
                previously_lost_paths,
                previously_stuck_active_paths,
            )

        # --- Phase 3b: Handle Side Effects (Reporting & Queuing) ---
        self._handle_scan_results_side_effects(
            newly_lost_paths=newly_lost_paths,
            newly_stuck_active_paths=newly_stuck_active_paths,
            removed_tracking_paths=removed_tracking_paths,
        )

        return next_file_states, currently_lost_paths, currently_stuck_active_paths

    def _handle_scan_results_side_effects(
        self,
        *,
        newly_lost_paths: Set[Path],
        newly_stuck_active_paths: Set[Path],
        removed_tracking_paths: Set[Path],
    ) -> None:
        """Orchestrates side effects: reporting changes and queuing newly 'lost' files."""
        try:
            report_state_changes(
                newly_lost_paths=newly_lost_paths,
                newly_stuck_active_paths=newly_stuck_active_paths,
                removed_tracking_paths=removed_tracking_paths,
                lost_timeout=self.lost_timeout,
                stuck_active_timeout=self.stuck_active_file_timeout,
            )
            # Only enqueue 'lost' files
            self._enqueue_lost_files(paths_to_enqueue=newly_lost_paths)
        except Exception:  # Error in reporting/queuing, log as EXCEPTION
            logger.exception(
                "Processor error during reporting or queuing phase for '%s'. Side effects may be incomplete.",
                self.directory_to_scan,
            )

    def _enqueue_lost_files(
        self, *, paths_to_enqueue: Set[Path]
    ) -> None:
        """Enqueues newly identified 'lost' file paths onto the lost_file_queue."""
        if not paths_to_enqueue:
            return

        # This is an action taken on potentially problematic files, so INFO is appropriate here.
        # It's not per-file in a tight loop, but a summary of an action.
        logger.info(
            "Processor enqueuing %d newly identified 'lost' files from '%s'",
            len(paths_to_enqueue),
            self.directory_to_scan,
        )
        for path in sorted(list(paths_to_enqueue)):
            try:
                safe_put(
                    item=path,
                    output_queue=self.lost_file_queue,
                    queue_name=self.lost_queue_name,
                )
                logger.info(
                    "Processor enqueued 'lost' file: %s", path
                )
            except QueuePutError as e:
                logger.error(
                    "Processor QueuePutError enqueuing 'lost' file '%s' for %s: %s",
                    path,
                    self.lost_queue_name,
                    e,
                )
            except (
                Exception
            ):  # Unexpected error during a specific put, log as EXCEPTION
                logger.exception(
                    "Processor unexpected error enqueuing 'lost' file '%s' for %s",
                    path,
                    self.lost_queue_name,
                )
