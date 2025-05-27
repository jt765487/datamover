import logging
from pathlib import Path
from queue import Queue
from typing import Callable, Dict, Set, Tuple, List

from datamover.file_functions.file_exceptions import ScanDirectoryError
from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.file_functions.scan_directory_and_filter import (
    scan_directory_and_filter,
)
from datamover.queues.queue_functions import safe_put, QueuePutError
from datamover.scanner.file_state_record import FileStateRecord
from datamover.scanner.process_scan_results import process_scan_results
from datamover.scanner.scan_reporting import report_state_changes
from datamover.scanner.stuck_app_reset import determine_app_restart_actions

logger = logging.getLogger(__name__)


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
        lost_file_queue: Queue[Path],
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
        self.lost_file_queue: Queue[Path] = lost_file_queue
        self.time_func: Callable[[], float] = time_func
        self.monotonic_func: Callable[[], float] = monotonic_func
        self.fs: FS = fs
        self.directory_to_scan: Path = validated_directory_to_scan
        self.lost_queue_name = f"LostFileQ-{self.directory_to_scan.name}"
        self.previously_signaled_stuck_apps: Set[str] = set()

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
        except Exception as e:
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
            currently_stuck_active_paths=currently_stuck_active_paths,
            removed_tracking_paths=removed_tracking_paths,
        )

        return next_file_states, currently_lost_paths, currently_stuck_active_paths

    def _handle_scan_results_side_effects(
        self,
        *,
        newly_lost_paths: Set[Path],
        newly_stuck_active_paths: Set[Path],  # For reporting via report_state_changes
        currently_stuck_active_paths: Set[Path],  # For determining restart triggers
        removed_tracking_paths: Set[Path],
    ) -> None:
        """Orchestrates side effects: reporting, queuing, and restart triggers."""
        try:
            report_state_changes(
                newly_lost_paths=newly_lost_paths,
                newly_stuck_active_paths=newly_stuck_active_paths,
                removed_tracking_paths=removed_tracking_paths,
                lost_timeout=self.lost_timeout,
                stuck_active_timeout=self.stuck_active_file_timeout,
            )
            self._enqueue_lost_files(paths_to_enqueue=newly_lost_paths)

            # --- Handle Restart Triggers for Stuck Applications ---
            logger.debug(
                "Determining restart actions for %d currently stuck active path(s). "
                "Previously signaled apps: %s",
                len(currently_stuck_active_paths),
                self.previously_signaled_stuck_apps
                if self.previously_signaled_stuck_apps
                else "None",
            )

            # current_stuck_file_paths from determine_app_restart_actions's perspective
            # is currently_stuck_active_paths from process_scan_results
            restart_files_to_create, next_signaled_stuck_apps = (
                determine_app_restart_actions(
                    current_stuck_file_paths=currently_stuck_active_paths,
                    previously_signaled_apps=self.previously_signaled_stuck_apps,
                    restart_trigger_directory=self.csv_restart_directory,
                )
            )

            if restart_files_to_create:
                # The number of files to create directly corresponds to the number of
                # unique applications newly identified as needing a signal.
                logger.info(
                    "Identified %d application(s) requiring a new restart trigger.",
                    len(restart_files_to_create),
                )
                self._create_restart_trigger_files(
                    files_to_create=restart_files_to_create
                )
            else:
                logger.debug(
                    "No new restart triggers required for stuck applications in this cycle."
                )

            # Update the set of signaled apps for the next cycle
            self.previously_signaled_stuck_apps = next_signaled_stuck_apps
            logger.debug(
                "Updated previously_signaled_stuck_apps for next cycle: %s",
                self.previously_signaled_stuck_apps
                if self.previously_signaled_stuck_apps
                else "None",
            )
        except Exception:  # Main try-except for all side effects
            logger.exception(
                "Processor error during side‐effects for '%s'. Some actions may be incomplete.",
                self.directory_to_scan,
            )

    def _enqueue_lost_files(self, *, paths_to_enqueue: Set[Path]) -> None:
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
        for path in sorted(paths_to_enqueue):
            try:
                safe_put(
                    item=path,
                    output_queue=self.lost_file_queue,
                    queue_name=self.lost_queue_name,
                )
                logger.info("Processor enqueued 'lost' file: %s", path)
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

    def _create_restart_trigger_files(self, *, files_to_create: Set[Path]) -> None:
        """
        Creates (touches) the specified .restart trigger files.

        Uses the configured filesystem abstraction (self.fs.open).
        Logs success for each created file and errors for any failures.
        Failures to create one file do not prevent attempts to create others.

        Args:
            files_to_create: A set of Path objects representing the full paths
                             to the .restart files that need to be created.
        """
        if not files_to_create:
            return

        logger.info(
            "Attempting to create %d restart trigger file(s)...", len(files_to_create)
        )
        created_count = 0
        failed_count = 0

        for restart_file_path in sorted(
            files_to_create
        ):  # Sort for consistent log order
            try:
                # Atomically create an empty .restart file if it does not already exist.
                # The 'a' mode creates if not exists, and updates timestamp if it does.
                with self.fs.open(restart_file_path, "a"):  # Using 'a' to create/touch
                    pass  # The file is created/timestamp updated by opening in 'a' or 'w'
                logger.info(
                    "Successfully created/updated restart trigger file: %s",
                    restart_file_path,
                )
                created_count += 1
            except Exception:  # Catch broad exceptions as per NFR2 for robustness
                logger.exception(
                    "Failed to create/update restart trigger file: %s",
                    restart_file_path,
                )
                failed_count += 1

        if created_count > 0:
            logger.info(
                "Finished creating/updating %d restart trigger file(s).", created_count
            )
        if failed_count > 0:
            logger.warning(
                "Failed to create/update %d restart trigger file(s). See previous errors.",
                failed_count,
            )
