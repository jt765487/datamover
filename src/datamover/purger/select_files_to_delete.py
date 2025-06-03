from typing import List

from datamover.file_functions.gather_entry_data import GatheredEntryData


def select_files_to_delete(
    *,
    all_files: List[GatheredEntryData],
    current_total_size: int,
    target_bytes_to_keep: int,
) -> List[GatheredEntryData]:
    """
    Pure function to select the oldest files to delete to reach the target disk usage.

    Args:
        all_files: A sorted list of files (oldest first).
        current_total_size: The current total size of the files.
        target_bytes_to_keep: The target disk space to keep.

    Returns:
        A list of files to delete (oldest first) to reach the target.
    """
    bytes_to_delete = current_total_size - target_bytes_to_keep
    if bytes_to_delete <= 0:
        return []

    files_to_delete = []
    deleted_size = 0
    for file_entry in all_files:
        files_to_delete.append(file_entry)
        deleted_size += file_entry.size
        if deleted_size >= bytes_to_delete:
            break
    return files_to_delete
