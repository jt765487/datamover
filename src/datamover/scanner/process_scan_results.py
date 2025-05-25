import logging
from pathlib import Path

from datamover.file_functions.gather_entry_data import (
    GatheredEntryData,
)

from datamover.scanner.file_state_record import (
    FileStateRecord,
    is_file_lost,
    is_active_since_last_scan,
    is_file_present_too_long,
)
from datamover.scanner.update_file_state_record import update_file_state_record

logger = logging.getLogger(__name__)


def process_scan_results(
    *,
    gathered_data: list[GatheredEntryData],
    existing_states: dict[Path, FileStateRecord],
    lost_timeout: float,
    stuck_active_timeout: float,
    monotonic_now: float,
    wall_now: float,
) -> tuple[
    dict[Path, FileStateRecord],  # next_file_states
    set[Path],  # removed_tracking_paths
    set[Path],  # currently_lost_paths
    set[Path],  # currently_stuck_active_paths (New return element)
]:
    """
    Processes directory scan results to update file states and identify problem files.

    This function takes files from the current scan (`gathered_data`) and compares
    them against previous states (`existing_states`). It performs several tasks:

    1.  **Updates File States: ** Utilizes `update_file_state_record` to create
        a new dictionary (`next_file_states`) reflecting the latest observed
        state of all files. This involves updating size/mtime for existing files
        (preserving `first_seen_mono` and setting `prev_scan_size`/`prev_scan_mtime_wall`
        from the old state) and creating records for new files (setting
        `first_seen_mono` to `monotonic_now` and `prev_scan_size`/`prev_scan_mtime_wall`
        to current values).

    2.  **Identifies Removed Files:** Determines which files tracked in
        `existing_states` are absent in `gathered_data`. These are returned as
        `removed_tracking_paths`.

    3.  **Identifies 'Lost' Files:** Iterates through `next_file_states`.
        For files also present in `existing_states` (i.e., not newly detected),
        it checks if they are 'lost' using `is_file_lost` (i.e., `mtime_wall`
        is older than `wall_now - lost_timeout`). These are added to
        `currently_lost_paths`. Newly detected files are not checked for 'lost'
        status in their first appearance cycle.

    4.  **Identifies 'Stuck Active' Files:** Iterates through `next_file_states`.
        A file is considered 'stuck active' if it meets two conditions:
        a. It has been active since the last scan (checked using
           `is_active_since_last_scan`).
        B. It has been present in the scan directory for longer than
           `stuck_active_timeout` (checked using `is_file_present_too_long`
           with `monotonic_now`).
        Files meeting both criteria are added to `currently_stuck_active_paths`.
        Note: A file typically won't be 'stuck active' in its first scan cycle
        due to how `is_active_since_last_scan` and `is_file_present_too_long`
        evaluate new files.

    Args:
        gathered_data: List of `GatheredEntryData` from the current scan.
        existing_states: Dictionary of `Path` to `FileStateRecord` from the
                         previous scan.
        lost_timeout: Duration (seconds) after which an unmodified file is 'lost'.
        stuck_active_timeout: Duration (seconds) after being first seen, beyond
                              which an *active* file is considered 'stuck active'.
        monotonic_now: Current monotonic time, for `first_seen_mono` of new files
                       and for checking `stuck_active_timeout`.
        wall_now: Current wall clock time, for checking `lost_timeout`.

    Returns:
        A tuple containing four elements:
        - next_file_states: Updated dictionary of file states.
        - removed_tracking_paths: Set of Paths no longer found.
        - currently_lost_paths: Set of Paths for files deemed 'lost'.
        - currently_stuck_active_paths: Set of Paths for files deemed 'stuck active'.
    """
    logger.debug(
        "Processing scan results with lost_timeout=%.1fs, stuck_active_timeout=%.1fs",
        lost_timeout,
        stuck_active_timeout,
    )

    # Step 1: Update states and identify files that disappeared.
    next_file_states, removed_tracking_paths = update_file_state_record(
        existing_file_states=existing_states,
        gathered_data=gathered_data,
        monotonic_time_now=monotonic_now,
    )

    logger.debug(
        "State update complete. Number of files being watched: %d, Removed tracking this cycle: %d",
        len(next_file_states),
        len(removed_tracking_paths),
    )

    # Step 2: Identify 'lost' and 'stuck active' files from the updated states.
    currently_lost_paths: set[Path] = set()
    currently_stuck_active_paths: set[Path] = set()

    lost_check_count = 0
    stuck_check_eligible_count = 0

    for path, state in next_file_states.items():
        # --- 'Lost' File Check ---
        if path in existing_states:
            lost_check_count += 1
            if is_file_lost(
                    state=state, wall_time_now=wall_now, lost_timeout=lost_timeout
            ):
                currently_lost_paths.add(path)
                logger.info(
                    "Identified a new file as LOST: %s (mtime: %s, age: %.1fs > %.1fs)",
                    path,
                    state.mtime_wall,
                    (wall_now - state.mtime_wall),
                    lost_timeout,
                )
                # Skip stuck‐active check for anything already lost
                continue

        # --- 'Stuck Active' File Check ---
        stuck_check_eligible_count += 1
        active = is_active_since_last_scan(record=state)
        present_too_long = is_file_present_too_long(
            state=state,
            monotonic_time_now=monotonic_now,
            presence_timeout=stuck_active_timeout,
        )

        if active and present_too_long:
            currently_stuck_active_paths.add(path)
            logger.info(
                "Identified file as STUCK ACTIVE: %s (first_seen_mono: %s, age_mono: %.1fs > %.1fs)",
                path,
                state.first_seen_mono,
                (monotonic_now - state.first_seen_mono),
                stuck_active_timeout,
            )
        elif present_too_long:
            # present too long but didn’t change
            logger.info(
                "File %s present too long (%.1fs) but NOT active.",
                path,
                (monotonic_now - state.first_seen_mono),
            )

    logger.debug(
        "Problem file checks complete. Lost eligible: %d, Found lost: %d. "
        "Stuck active eligible: %d, Found stuck active: %d.",
        lost_check_count,
        len(currently_lost_paths),
        stuck_check_eligible_count,
        len(currently_stuck_active_paths),
    )

    return (
        next_file_states,
        removed_tracking_paths,
        currently_lost_paths,
        currently_stuck_active_paths,
    )
