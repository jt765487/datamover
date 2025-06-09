import logging
from datetime import datetime
from typing import List

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.file_functions.safe_delete import safe_delete, DeleteValidationError
from datamover.purger.select_files_to_delete import select_files_to_delete

logger = logging.getLogger(__name__)


def _format_size_human_readable(size_bytes: int) -> str:
    """Converts a size in bytes to a human-readable string (KB, MB, GB, etc.)."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    for unit in ["KB", "MB", "GB", "TB"]:
        size_bytes /= 1024
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
    return f"{size_bytes:.2f} PB"


def process_files_for_deletion(
    *,
    files_to_consider: List[GatheredEntryData],
    fs: FS,
    directory_description: str,
    target_bytes_to_keep: int,
) -> int:
    """Selects and attempts to delete files from a given list."""
    if not files_to_consider:
        logger.info(f"No files in {directory_description} to process for deletion.")
        return 0

    current_size = sum(f.size for f in files_to_consider)
    files_to_delete = select_files_to_delete(
        all_files=files_to_consider,
        current_total_size=current_size,
        target_bytes_to_keep=target_bytes_to_keep,
    )
    logger.info(
        f"Selected {len(files_to_delete)} files from {directory_description} for potential deletion."
    )

    bytes_actually_deleted = 0
    for file_entry in files_to_delete:
        try:
            safe_delete(file_entry.path, fs)

            # Format the size and modification time for the log message
            readable_size = _format_size_human_readable(file_entry.size)
            readable_mtime = datetime.fromtimestamp(file_entry.mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            logger.info(
                f"Successfully deleted: {file_entry.path} "
                f"(size: {readable_size}, mtime: {readable_mtime}) "
                f"from {directory_description}."
            )

            bytes_actually_deleted += file_entry.size
        except DeleteValidationError as e:
            logger.warning(
                f"Could not delete file {file_entry.path} from {directory_description}: {e}. Skipping."
            )
        except Exception as ex:
            logger.error(
                f"Unexpected error deleting file {file_entry.path} from {directory_description}: {ex}. Skipping.",
                exc_info=True,
            )

    if bytes_actually_deleted > 0:
        logger.info(
            f"Actually deleted {bytes_actually_deleted} bytes from {directory_description}."
        )
    return bytes_actually_deleted
