import logging
import os
from pathlib import Path
from typing import Optional

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.safe_stat import safe_stat

logger = logging.getLogger(__name__)


def validate_file(
    source_path_input: Path,
    expected_source_dir: Path,
    fs: FS,
) -> Optional[Path]:
    """
    Validates a source file path against configured expectations using FS object.

    Checks type (statically), existence, file type (regular file), symlinks,
    readability, and confinement within the expected_source_dir. Logs errors
    on failure.

    Args:
        source_path_input: The Path object for the source file to validate.
        expected_source_dir: The *resolved* Path object for the directory
                             where the source file must reside.
        fs: The FS dependency object providing lstat, resolve, access.

    Returns:
        The *resolved* absolute Path object if validation passes, None otherwise.
    """
    # --- Initial Checks via safe_stat (which uses fs.lstat) ---
    stat_info: Optional[tuple[int, int]] = safe_stat(source_path_input, fs=fs)
    if stat_info is None:
        logger.error(
            "Validation failed: Initial checks via safe_stat failed for '%s'. See prior logs.",
            source_path_input,
        )
        return None

    # --- Resolve and perform remaining checks using FS ---
    try:
        resolved_source_path: Path = fs.resolve(source_path_input, strict=True)

        # Confinement Check (logic unchanged)
        if resolved_source_path.parent != expected_source_dir:
            logger.error(
                "Validation failed: Resolved path '%s' is not directly within expected directory '%s'.",
                resolved_source_path,
                expected_source_dir,
            )
            return None

        if not fs.access(resolved_source_path, os.R_OK):
            logger.error(
                "Validation failed: Source path '%s' is not readable.",
                resolved_source_path,
            )
            return None

        # --- All checks passed ---
        return resolved_source_path

    except FileNotFoundError as e:
        # Can be raised by fs.resolve(strict=True)
        logger.warning(
            "Validation failed: File not found during resolve/access check for '%s': %s",
            source_path_input,
            e,
        )
        return None
    except OSError as e:
        # Can be raised by fs.resolve or fs.access
        logger.error(
            "Validation failed: OS error during resolve or access check for '%s': %s",
            source_path_input,
            e,
        )
        return None
    except Exception as e:
        # Catch other unexpected errors from FS methods
        logger.error(
            "Validation failed: Unexpected error during resolve/access check for '%s': %s",
            source_path_input,
            e,
        )
        return None
