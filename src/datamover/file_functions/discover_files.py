import logging
from pathlib import Path
from typing import Set

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.safe_stat import safe_stat

logger = logging.getLogger(__name__)


def discover_files(directory_path: Path, fs: FS) -> Set[Path]:
    """
    Discovers initial regular files directly within the given directory using
    injected FS functions. Returns Path objects.

    Args:
        directory_path: A Path object representing the directory to scan.
        fs: The FS dependency object.

    Returns:
        A set of Path objects for regular files found directly in the directory.
        Returns an empty set on directory listing errors.
    """
    discovered_files: Set[Path] = set()  # <-- Set now holds Path objects
    logger.debug("Discovering initial files in directory: %s", directory_path)
    try:
        for name in fs.listdir(directory_path):
            child_path_obj: Path = directory_path / name
            try:
                stat_result = safe_stat(child_path_obj, fs)

                if stat_result:  # If regular file and stat successful
                    discovered_files.add(child_path_obj)
                    logger.debug("Discovered initial file: %s", child_path_obj)

            except OSError as e:
                logger.warning(
                    "Error processing potential file %s: %s", child_path_obj, e
                )
            except Exception:
                logger.exception("Unexpected error processing item %s", child_path_obj)

    except OSError as e:
        logger.error("Cannot list directory %s: %s", directory_path, e)
        return set()
    except Exception:
        logger.exception("Unexpected error discovering files in %s", directory_path)
        return set()

    logger.info(
        "Discovery complete. Found %d initial files in %s.",
        len(discovered_files),
        directory_path,
    )
    return discovered_files
