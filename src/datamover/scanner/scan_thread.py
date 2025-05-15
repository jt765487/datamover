import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Union, Optional

from datamover.file_functions.file_exceptions import ScanDirectoryError

from datamover.protocols import SleepCallable

from datamover.scanner.file_state_record import FileStateRecord
from datamover.scanner.do_single_cycle import DoSingleCycle

logger = logging.getLogger(__name__)


class ScanThread(threading.Thread):
    """
    A background thread that periodically triggers a directory scan cycle.

    This thread manages the timing of scan intervals, maintains the state of
    monitored files (including 'lost' and 'stuck active' statuses) between
    cycles, and ensures a graceful shutdown process when signaled. It delegates
    the core logic of a single scan cycle to an injected `DoSingleCycle` processor.
    """

    def __init__(
        self,
        *,
        processor: DoSingleCycle,
        stop_event: threading.Event,
        scan_interval_seconds: float,
        sleep_func: SleepCallable,
        monotonic_func: Callable[[], float],
        name: str,
    ):
        """
        Initializes the ScanThread.

        Args:
            processor: An instance of `DoSingleCycle` that performs the logic
                       for a single scan. It's expected to have attributes like
                       `directory_to_scan`, `lost_timeout`,
                       `stuck_active_file_timeout`, and `lost_queue_name`
                       for logging and configuration context.
            stop_event: A `threading.Event` used to signal the thread to stop.
            scan_interval_seconds: The target interval between the start of
                                   consecutive scan cycles.
            sleep_func: A callable for pausing execution (e.g., `time.sleep`),
                        used by `stop_event.wait()`.
            monotonic_func: A callable returning current monotonic time
                            (e.g., `time.monotonic()`), used for cycle timing.
            name: The name for this thread.
        """
        super().__init__(daemon=True, name=name)

        self.processor: DoSingleCycle = processor
        self.scan_interval_seconds: float = scan_interval_seconds
        self.stop_event: threading.Event = stop_event
        self.sleep_func: SleepCallable = (
            sleep_func  # Stored but primarily used via stop_event.wait
        )
        self.monotonic_func: Callable[[], float] = monotonic_func

        # Internal state persisted cross scan cycles
        self._current_file_states: dict[Path, FileStateRecord] = {}
        self._previously_lost_paths: set[Path] = set()
        self._previously_stuck_active_paths: set[Path] = set()

        # Attributes derived from the processor for logging context
        self.log_scan_dir: Union[Path, str] = getattr(
            self.processor, "directory_to_scan", "UnknownDir"
        )
        self.log_lost_timeout: Union[float, str] = getattr(
            self.processor, "lost_timeout", "N/A"
        )
        self.log_stuck_timeout: Union[float, str] = getattr(
            self.processor, "stuck_active_file_timeout", "N/A"
        )
        self.log_lost_queue_name: str = getattr(
            self.processor, "lost_queue_name", "UnknownQ"
        )

        # Single INFO log for thread initialization summary
        logger.info(
            "Initialized %s for '%s' [Interval: %.1fs, Lost Timeout: %s, "
            "Stuck Active Timeout: %s, Lost File Queue: %s]",
            self.name,
            self.log_scan_dir,
            self.scan_interval_seconds,
            self.log_lost_timeout,
            self.log_stuck_timeout,
            self.log_lost_queue_name,
        )

    def run(self) -> None:
        """
        The main execution loop for the scanning thread.

        Periodically:
        1. Triggers the `DoSingleCycle` processor.
        2. Logs newly identified 'stuck active' files as CRITICAL.
        3. Updates its internal tracking states (`_current_file_states`,
           `_previously_lost_paths`, `_previously_stuck_active_paths`).
        4. Waits for the next scan interval or until a stop signal is received.
        Handles critical `ScanDirectoryError` by stopping the thread and logs
        other unexpected errors while attempting to continue.
        """
        iteration: int = 0
        logger.info("Starting %s monitoring '%s'", self.name, self.log_scan_dir)

        # Use the thread's own injected monotonic_func for timing the loop
        monotonic_func = self.monotonic_func

        while not self.stop_event.is_set():
            iteration += 1
            start_time: float = monotonic_func()
            # Repetitive per-cycle log, keep as DEBUG
            logger.debug(
                "%s cycle %d starting for '%s'", self.name, iteration, self.log_scan_dir
            )

            next_states: Optional[dict[Path, FileStateRecord]] = None
            current_lost: Optional[set[Path]] = None
            current_stuck: Optional[set[Path]] = None
            cycle_success: bool = False

            try:
                # Delegate to the processor for one scan cycle
                (
                    next_states,
                    current_lost,
                    current_stuck,
                ) = self.processor.process_one_cycle(
                    current_file_states=self._current_file_states,
                    previously_lost_paths=self._previously_lost_paths,
                    previously_stuck_active_paths=self._previously_stuck_active_paths,
                )
                cycle_success = True

            except ScanDirectoryError as e:
                # Critical error related to accessing the scan directory
                logger.error(
                    "%s: Critical ScanDirectoryError for '%s': %s. Original: %s. Thread stopping.",
                    self.name,
                    getattr(e, "directory", self.log_scan_dir),
                    e,
                    getattr(e, "original_exception", "N/A"),
                )
                break  # Exit the main loop

            except Exception:
                # Other unexpected errors during processor execution
                logger.exception(
                    "%s: Unexpected error during processor cycle for '%s'; state not updated for this cycle.",
                    self.name,
                    self.log_scan_dir,
                )
                # cycle_success remains False, state update will be skipped

            # Log newly identified stuck active files as CRITICAL
            if cycle_success and current_stuck is not None:
                newly_stuck_this_cycle = (
                    current_stuck - self._previously_stuck_active_paths
                )
                if newly_stuck_this_cycle:
                    # CRITICAL log for a potentially serious condition
                    logger.critical(
                        "%s detected NEWLY STUCK ACTIVE files in '%s' (active & present > %s sec): %s",
                        self.name,
                        self.log_scan_dir,
                        self.log_stuck_timeout,  # Use the stored timeout value for the log
                        sorted(list(p.as_posix() for p in newly_stuck_this_cycle)),
                    )

            # Update internal state if the cycle was successful
            if (
                cycle_success
                and next_states is not None
                and current_lost is not None
                and current_stuck is not None
            ):
                self._update_state(next_states, current_lost, current_stuck)
            elif not cycle_success:
                # WARNING if a cycle fails but the thread continues
                logger.warning(
                    "%s cycle %d for '%s' did not complete successfully, state not updated.",
                    self.name,
                    iteration,
                    self.log_scan_dir,
                )

            end_time: float = monotonic_func()
            cycle_duration: float = end_time - start_time
            # Repetitive per-cycle log, keep as DEBUG
            logger.debug(
                "%s cycle %d for '%s' finished (took %.3f sec, success: %s)",
                self.name,
                iteration,
                self.log_scan_dir,
                cycle_duration,
                cycle_success,
            )
            self._wait_or_stop(cycle_duration)

        # Single INFO log for thread stop
        logger.info(
            "Stopping %s monitoring for '%s' - Graceful exit after %d iterations.",
            self.name,
            self.log_scan_dir,
            iteration,
        )

    def stop(self) -> None:
        """Signals the thread to stop its scanning loop gracefully."""
        if not self.stop_event.is_set():
            # INFO log for a significant lifecycle event
            logger.info("%s received stop signal, requesting shutdown.", self.name)
            self.stop_event.set()
        else:
            # DEBUG if already stopping
            logger.debug("%s is already stopping or has stopped.", self.name)

    def _wait_or_stop(self, cycle_duration: float) -> None:
        """
        Waits for the remainder of the scan interval or stops if signaled.
        Uses `stop_event.wait()` for interruptible waiting.
        """
        if self.stop_event.is_set():  # Check before attempting to wait
            return

        wait_time: float = max(0.0, self.scan_interval_seconds - cycle_duration)

        if wait_time > 0:
            # Repetitive per-cycle log, keep as DEBUG
            logger.debug(
                "%s waiting %.3f seconds before next scan cycle.", self.name, wait_time
            )
            interrupted: bool = self.stop_event.wait(wait_time)
            if interrupted:
                # INFO log if wait is interrupted by stop signal
                logger.info("%s wait interrupted by stop signal.", self.name)
        else:
            # Repetitive per-cycle log (if cycle > interval), keep as DEBUG
            logger.debug(
                "%s scan cycle duration (%.3f sec) met or exceeded interval (%.1f sec), starting next cycle immediately.",
                self.name,
                cycle_duration,
                self.scan_interval_seconds,
            )

    def _update_state(
        self,
        next_states: dict[Path, FileStateRecord],
        currently_lost_paths: set[Path],
        currently_stuck_active_paths: set[Path],
    ) -> None:
        """
        Atomically updates the thread's internal tracking states for the next cycle.
        Assignments of built-in types like dicts and sets are atomic in Python.
        """
        self._current_file_states = next_states
        self._previously_lost_paths = currently_lost_paths
        self._previously_stuck_active_paths = currently_stuck_active_paths

        # Repetitive per-cycle log, keep as DEBUG
        logger.debug(
            "%s internal state updated: %d tracked, %d lost, %d stuck active.",
            self.name,
            len(self._current_file_states),
            len(self._previously_lost_paths),
            len(self._previously_stuck_active_paths),
        )
