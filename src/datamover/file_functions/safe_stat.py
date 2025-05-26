import logging
import stat
import os
from pathlib import Path
from typing import Optional

from datamover.file_functions.fs_mock import FS

logger = logging.getLogger(__name__)


def safe_stat(
    path: Path,
    fs: FS,
) -> Optional[tuple[int, int]]:
    """
    Safely get inode and size IF the path points DIRECTLY to a regular file.

    Uses lstat() via the injected FS object to avoid following symbolic links.
    Returns None if the path does not exist, is not accessible, is not a
    regular file (e.g., directory, symlink, socket), or if an error occurs.

    Args:
        path: The file path (must be a Path object). # <-- Updated docstring
        fs: The FS dependency object providing lstat.

    Returns:
        Tuple (inode, size) if path is a regular file, None otherwise.
    """
    try:
        # Use lstat to get info about the entry itself (symlink or file/dir etc.)
        # fs.lstat is expected to return os.stat_result
        stat_result: os.stat_result = fs.lstat(path)

        # Check if the mode indicates it IS a regular file (and NOT a symlink, etc.)
        if not stat.S_ISREG(stat_result.st_mode):
            logger.debug("Path is not a regular file (lstat check): %s", path)
            return None

        # It is a regular file
        return stat_result.st_ino, stat_result.st_size

    except FileNotFoundError:
        logger.info("safe_stat (lstat): File not found: %s", path)
        return None
    except OSError as e:
        logger.info("safe_stat (lstat) failed for %s: %s", path, e)
        return None
    except Exception:
        logger.exception("Unexpected error during safe_stat (lstat) for %s:", path)
        return None
