from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileStateRecord:
    """
    An immutable record representing the observed state of a file at a specific
    point in time during a scan cycle, including details from the previous scan.

    This record is designed to track changes in file properties (size, modification
    time) between scan cycles and to note when a file was first observed by the
    monitoring process.

    Attributes:
        path: The absolute Path to the file.
        size: The size of the file in bytes as observed in the current scan cycle.
        mtime_wall: The last modification time (wall clock, e.g., from os.stat().st_mtime)
                    of the file as observed in the current scan cycle.
        first_seen_mono: The monotonic clock time (e.g., from time.monotonic()) when
                         this file path was first detected by the monitoring process.
                         This time is preserved across subsequent scans for the same path.
        prev_scan_size: The size of the file in bytes as observed in the *previous*
                        scan cycle. For newly detected files, this is initialized
                        to the file's current size in its first record.
        prev_scan_mtime_wall: The last modification time (wall clock) of the file
                              as observed in the *previous* scan cycle. For newly
                              detected files, this is initialized to the file's
                              current mtime in its first record.
    """

    path: Path
    size: int
    mtime_wall: float
    first_seen_mono: float
    prev_scan_size: int
    prev_scan_mtime_wall: float


def is_file_lost(
    state: FileStateRecord, wall_time_now: float, lost_timeout: float
) -> bool:
    """
    Determines if a file is considered 'lost' based on its last modification time.

    A file is defined as 'lost' if its content (indicated by `mtime_wall`) has
    not been updated for a duration exceeding the `lost_timeout`. This typically
    identifies files that were expected to be processed or moved but were missed.

    Args:
        state: The `FileStateRecord` of the file to check.
        wall_time_now: The current wall clock time (e.g., from `time.time()`),
                       used as the reference point for calculating age.
        lost_timeout: The threshold in seconds. If the time since `state.mtime_wall`
                      is greater than this value, the file is considered lost.

    Returns:
        True if the file is considered lost, False otherwise.
    """
    return (wall_time_now - state.mtime_wall) > lost_timeout


def is_active_since_last_scan(record: FileStateRecord) -> bool:
    """
    Checks if the file has shown activity (size or mtime change) since the previous scan.

    Activity is defined as a change in the file's size or its last modification
    time (`mtime_wall`) when comparing the current scan's observations (`record.size`,
    `record.mtime_wall`) with those from the immediately preceding scan
    (`record.prev_scan_size`, `record.prev_scan_mtime_wall`).

    For files observed for the first time in a scan cycle, their `prev_scan_size`
    and `prev_scan_mtime_wall` are initialized to their current `size` and
    `mtime_wall` respectively. Consequently, such newly seen files will
    return `False` from this function in their initial `FileStateRecord`, as no
    change *between scans* has yet been observed.

    Args:
        record: The `FileStateRecord` for the file from the current scan cycle.

    Returns:
        True if the file's size or mtime has changed compared to the state
        recorded in the previous scan cycle, False otherwise.
    """
    return (
        record.size != record.prev_scan_size
        or record.mtime_wall != record.prev_scan_mtime_wall
    )


def is_file_present_too_long(
    state: FileStateRecord, monotonic_time_now: float, presence_timeout: float
) -> bool:
    """
    Checks if a file has been known to the monitoring process for too long.

    This function determines if the duration since the file was *first seen* by
    the monitoring process (tracked by `state.first_seen_mono` using a monotonic
    clock) has exceeded the specified `presence_timeout`.

    This check is independent of whether the file is currently active or
    has changed recently. It solely measures the total time the file path
    has been under observation by this specific monitoring instance.

    Args:
        state: The `FileStateRecord` of the file to check.
        monotonic_time_now: The current monotonic time (e.g., from `time.monotonic()`),
                            used as the reference for calculating duration since first seen.
        presence_timeout: The threshold in seconds. If the time since
                          `state.first_seen_mono` is greater than this value,
                          the file is considered present for too long.

    Returns:
        True if the file has been present longer than the `presence_timeout`,
        False otherwise.
    """
    time_since_seen = monotonic_time_now - state.first_seen_mono
    is_past_timeout = time_since_seen > presence_timeout
    return is_past_timeout
