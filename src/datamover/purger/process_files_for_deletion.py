import logging
from typing import List

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.file_functions.safe_delete import safe_delete, DeleteValidationError
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
            logger.info(
                f"Successfully deleted: {file_entry.path} (freed: {file_entry.size} bytes) from {directory_description}."
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
