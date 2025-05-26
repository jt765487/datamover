import logging
from pathlib import Path

from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.scanner.file_state_record import FileStateRecord

logger = logging.getLogger(__name__)


def update_file_state_record(
    existing_file_states: dict[Path, FileStateRecord],
    gathered_data: list[GatheredEntryData],
    monotonic_time_now: float,
) -> tuple[dict[Path, FileStateRecord], set[Path]]:
    """
    Creates an updated collection of file states based on newly gathered directory data.

    This function compares file information from the current scan (`gathered_data`)
    against previously known states (`existing_file_states`) to produce a new
    set of `FileStateRecord` objects. It also identifies paths that were tracked
    previously but are no longer present in the current scan.

    Key behaviors:
    - For files previously seen:
        - `first_seen_mono` is preserved from the `old_state`.
        - `prev_scan_size` and `prev_scan_mtime_wall` in the new `FileStateRecord`
          are populated from the `size` and `mtime_wall` of the `old_state`
          (i.e., the actual values from the previous scan).
    - For newly detected files:
        - `first_seen_mono` is set to `monotonic_time_now`.
        - `prev_scan_size` and `prev_scan_mtime_wall` are initialized with the
          file's current `size` and `mtime_wall` from `gathered_data`. This ensures
          that `is_active_since_last_scan()` will return `False` for such files
          in their first `FileStateRecord`, as no inter-scan change has yet been observed.

    This function operates immutably; it does not modify the input
    `existing_file_states` dictionary.

    Args:
        existing_file_states: A dictionary mapping file Paths to their
                               `FileStateRecord` from the previous scan cycle.
        gathered_data: A list of `GatheredEntryData` objects, representing
                       files found and their properties (path, size, mtime)
                       from the current directory scan.
        monotonic_time_now: The current monotonic time (e.g., from `time.monotonic()),
                            used to timestamp `first_seen_mono` for new files and
                            potentially for other time-sensitive logic within the scan cycle.

    Returns:
        A tuple containing:
        - Next_file_states (Dict[Path, FileStateRecord]): a new dictionary mapping
          file Paths to their updated `FileStateRecord` objects.
        - Removed_paths (Set[Path]): A set of Paths that were keys in
          `existing_file_states` but were not found in `gathered_data`
          (these files are no longer seen in the scanned directory).
    """
    new_file_states: dict[Path, FileStateRecord] = {}
    gathered_paths: set[Path] = set()  # Keep track of paths seen in this scan

    for entry_data in gathered_data:
        path: Path = entry_data.path
        gathered_paths.add(path)

        if path in existing_file_states:
            old_state: FileStateRecord = existing_file_states[path]
            updated_state: FileStateRecord = FileStateRecord(
                path=path,
                size=entry_data.size,  # Current size from this scan
                mtime_wall=entry_data.mtime,  # Current mtime from this scan
                first_seen_mono=old_state.first_seen_mono,  # Preserve original discovery time
                prev_scan_size=old_state.size,  # Size from the actual previous scan
                prev_scan_mtime_wall=old_state.mtime_wall,  # Mtime from the actual previous scan
            )
            new_file_states[path] = updated_state
        else:
            # New file detected in this scan
            # Initialize prev_scan_ fields to current values so no "change" is detected in its first record.
            new_state: FileStateRecord = FileStateRecord(
                path=path,
                size=entry_data.size,
                mtime_wall=entry_data.mtime,
                first_seen_mono=monotonic_time_now,  # Record discovery monotonic time
                prev_scan_size=entry_data.size,
                prev_scan_mtime_wall=entry_data.mtime,
            )
            new_file_states[path] = new_state

    # Identify paths that were in the old state but not found in the current scan
    removed_paths: set[Path] = set(existing_file_states.keys()) - gathered_paths

    return new_file_states, removed_paths
