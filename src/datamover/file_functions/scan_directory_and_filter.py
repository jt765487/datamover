import logging
from pathlib import Path

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import (
    GatheredEntryData,
    gather_file_data,
)

logger = logging.getLogger(__name__)


def scan_directory_and_filter(
    directory: Path, fs: FS, extension_no_dot: str
) -> list[GatheredEntryData]:
    """
    Scans the directory using gather_file_data and filters the results
    for files with the expected extension (case-insensitive).

    Args:
        directory: The directory path to scan.
        fs: An instance of the FS abstraction.
        extension_no_dot: The required file extension (lowercase, no leading dot).

    Returns:
        A list of GatheredEntryData for matching files.

    Raises:
        ScanDirectoryError: If gather_file_data fails critically.
    """
    # gather_file_data might raise ScanDirectoryError - let it propagate
    all_gathered_data = gather_file_data(directory=directory, fs=fs)

    expected_suffix = f".{extension_no_dot.lower()}"
    filtered_data = [
        entry
        for entry in all_gathered_data
        if entry.path.suffix.lower() == expected_suffix
    ]
    logger.debug(
        "Filtered %d gathered entries down to %d matching suffix '%s'",
        len(all_gathered_data),
        len(filtered_data),
        expected_suffix,
    )
    return filtered_data
