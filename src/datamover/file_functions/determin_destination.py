import logging
from pathlib import Path
from typing import Optional

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.find_available_target_path import (
    find_available_target_path,
)

logger = logging.getLogger(__name__)


def determine_destination(
    initial_dest_path: Path,
    source_name_for_log: str,
    fs: FS,
) -> Optional[Path]:
    """
    Checks initial proposed path existence using fs.exists(). If it exists,
    resolves conflict using find_available_target_path internally.

    Args:
        initial_dest_path: The desired destination Path object.
        source_name_for_log: Original source filename for context in logs.
        fs: The FS object providing .exists() passed down to helpers.

    Returns:
        An available Path object (original or unique), or None if unavailable
        after checking or if the finding process failed.
    """
    try:
        path_exists = fs.exists(initial_dest_path)

        if not path_exists:
            logger.debug(
                "Initial destination path '%s' is available.", initial_dest_path
            )
            return initial_dest_path  # Original path is fine
        else:
            logger.warning(
                "Proposed path '%s' already exists (for source '%s'). Attempting conflict resolution...",
                initial_dest_path,
                source_name_for_log,
            )
            unique_target: Optional[Path] = find_available_target_path(
                base_path=initial_dest_path, fs=fs
            )

            if unique_target:
                logger.info(
                    "Conflict resolved for '%s'. Using unique path: '%s'",
                    source_name_for_log,
                    unique_target,
                )
                return unique_target
            else:
                # find_available_target_path failed and logged the specific reason.
                logger.error(
                    "CONFLICT RESOLUTION FAILED for file '%s' based on target '%s'.",
                    source_name_for_log,
                    initial_dest_path.name,
                )
                return None  # Signal failure

    except OSError as e_fs:
        logger.error(
            "OSError checking/determining destination path based on '%s' for '%s': %s",
            initial_dest_path,
            source_name_for_log,
            e_fs,
        )
        return None
    except Exception:
        logger.exception(
            "Unexpected error determining destination path based on '%s' for '%s'",
            initial_dest_path,
            source_name_for_log,
        )
        return None
