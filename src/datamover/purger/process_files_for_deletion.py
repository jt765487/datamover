import logging
from datetime import datetime
from typing import List

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.file_functions.safe_delete import safe_delete, DeleteValidationError
from datamover.purger.format_size_human_readable import format_size_human_readable
from datamover.purger.select_files_to_delete import select_files_to_delete

logger = logging.getLogger(__name__)


def process_files_for_deletion(
    *,
    files_to_consider: List[GatheredEntryData],
    fs: FS,
    directory_description: str,
    target_bytes_to_keep: int,
) -> int:
    """Selects and attempts to delete files from a given list."""
    if not files_to_consider:
        logger.info("No files in %s to process for deletion.", directory_description)
        return 0

    current_size = sum(f.size for f in files_to_consider)
    files_to_delete = select_files_to_delete(
        all_files=files_to_consider,
        current_total_size=current_size,
        target_bytes_to_keep=target_bytes_to_keep,
    )
    logger.info(
        "Selected %s files from %s for potential deletion.",
        len(files_to_delete),
        directory_description,
    )

    bytes_actually_deleted = 0
    for file_entry in files_to_delete:
        try:
            safe_delete(file_entry.path, fs)

            # Format the size and modification time for the log message
            readable_size = format_size_human_readable(file_entry.size)
            readable_mtime = datetime.fromtimestamp(file_entry.mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            logger.info(
                "Successfully deleted: %s (size: %s, time: %s) from %s.",
                file_entry.path,
                readable_size,
                readable_mtime,
                directory_description,
            )

            bytes_actually_deleted += file_entry.size
        except DeleteValidationError as e:
            logger.warning(
                f"Could not delete file {file_entry.path} from {directory_description}: {e}. Skipping."
            )
        except Exception as ex:
            logger.error(
                "Unexpected error deleting file %s from %s: %s. Skipping.",
                file_entry.path,
                directory_description,
                ex,
                exc_info=True,
            )

    if bytes_actually_deleted > 0:
        readable_deleted = format_size_human_readable(bytes_actually_deleted)
        logger.info(
            "Actually deleted %s from %s.", readable_deleted, directory_description
        )

    return bytes_actually_deleted
