import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def report_newly_lost(file_paths: set[Path], timeout: float) -> None:
    """Logs files that have newly become 'lost' (stale/unmodified > timeout)."""
    if file_paths:
        logger.warning(
            "Newly detected LOST files (unmodified > %.1f sec): %s",
            timeout,
            sorted(list(p.as_posix() for p in file_paths)),  # Consistent sorting
        )


def report_newly_stuck_active(file_paths: set[Path], timeout: float) -> None:
    """Logs files that have newly become 'stuck active' (active + present > timeout)."""
    if file_paths:
        logger.warning(
            "Newly detected STUCK ACTIVE files (active & present > %.1f sec): %s",
            timeout,
            sorted(list(p.as_posix() for p in file_paths)),  # Consistent sorting
        )


def report_removed_from_tracking(file_paths: set[Path]) -> None:
    """Logs files newly removed from tracking (were tracked, now missing from scan)."""
    if file_paths:
        logger.info(
            "Files REMOVED from tracking (previously tracked, now missing from scan): %s",
            sorted(list(p.as_posix() for p in file_paths)),  # Consistent sorting
        )


def report_state_changes(
    *,
    newly_lost_paths: set[Path],
    newly_stuck_active_paths: set[Path],
    removed_tracking_paths: set[Path],
    lost_timeout: float,
    stuck_active_timeout: float,
) -> None:
    """
    Logs summaries of newly identified problem files and files removed from tracking.

    This function serves as a central point for reporting different categories of
    file state changes identified during a scan cycle. It delegates to more
    specific reporting functions for each category.

    Args:
        newly_lost_paths: Set of paths for files newly identified as 'lost'.
        newly_stuck_active_paths: Set of paths for files newly identified as
                                  'stuck active'.
        removed_tracking_paths: Set of paths for files that were previously
                                tracked but are no longer found in the scan.
        lost_timeout: The timeout value (seconds) used to define 'lost' files.
        stuck_active_timeout: The timeout value (seconds) used to define
                              'stuck active' files.
    """
    report_newly_lost(file_paths=newly_lost_paths, timeout=lost_timeout)
    report_newly_stuck_active(
        file_paths=newly_stuck_active_paths, timeout=stuck_active_timeout
    )
    report_removed_from_tracking(file_paths=removed_tracking_paths)
