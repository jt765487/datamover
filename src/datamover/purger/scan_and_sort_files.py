import logging
from pathlib import Path
from typing import List, Tuple

from datamover.file_functions.file_exceptions import ScanDirectoryError
from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import (
    GatheredEntryData,
    gather_file_data,
)

logger = logging.getLogger(__name__)


def scan_and_sort_files(
    directory_path: Path, fs: FS, description: str
) -> Tuple[List[GatheredEntryData], bool]:
    """Scans a directory, sorts the files by mtime, and handles potential errors."""
    files_sorted: List[GatheredEntryData] = []
    scan_ok = True
    try:
        logger.debug("Scanning %s directory: %s", description, directory_path)
        files_sorted = gather_file_data(directory_path, fs)
        files_sorted.sort()
        logger.info(
            "Found and sorted %d files in %s directory.", len(files_sorted), description
        )
    except ScanDirectoryError as e:
        logger.error(
            "Error scanning %s directory %s: %s.", description, directory_path, e
        )
        scan_ok = False
    return files_sorted, scan_ok
