import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from datamover.file_functions.file_exceptions import ScanDirectoryError
from datamover.file_functions.fs_mock import FS

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class GatheredEntryData:
    """
    Holds essential stat info for successfully processed regular files.
    Instances are ordered primarily by mtime, then by size. Path is ignored
    for comparison and sorting purposes.
    """

    mtime: float
    size: int
    path: Path = field(compare=False)


def gather_file_data(directory: Path, fs: FS) -> list[GatheredEntryData]:
    """
    Implementation of the FileScanner protocol.

    Scans a directory using the injected FS abstraction, returning data for
    regular files found directly within that directory.

    Symlinks, subdirectories, and other non-regular file types are ignored.
    Uses fs.scandir for efficient directory iteration and fs.resolve for
    canonical paths. Errors processing individual entries are logged, and
    processing continues for others.

    Args:
        directory: The directory path to scan.
        fs: An instance of the FS abstraction providing filesystem operations.

    Returns:
        A list of GatheredEntryData instances for each valid regular file found.
        Returns an empty list if the directory is empty or contains no
        eligible regular files but was successfully scanned.

    Raises:
        ScanDirectoryError: If the directory cannot be scanned due to issues like
                           permissions, non-existence, or not being a directory,
                           wrapping the original low-level exception.
    """
    logger.debug("Gathering file data in directory: %s", directory)
    gathered_data: list[GatheredEntryData] = []

    try:
        # Use the scandir provided by the FS abstraction.
        with fs.scandir(directory) as scanner:
            for entry in scanner:
                entry_name = entry.name  # Cache name for logging
                try:
                    # 1. Check if it's a regular file (and not a symlink)
                    if entry.is_file(follow_symlinks=False):
                        # 2. Get stat results (size, mtime)
                        stats: os.stat_result = entry.stat(follow_symlinks=False)

                        # 3. Resolve the path using the FS abstraction
                        raw_path = Path(entry.path)
                        resolved_path = fs.resolve(raw_path, strict=False)

                        # 4. Create and store the data object
                        gathered_data.append(
                            GatheredEntryData(
                                mtime=stats.st_mtime,  # Ensure correct order for constructor
                                size=stats.st_size,
                                path=resolved_path,
                            )
                        )
                        logger.debug("Gathered data for: %s", resolved_path)

                # --- Handle errors for THIS specific entry - LOG AND CONTINUE ---
                except OSError as entry_error:
                    # Log warning without exception info to keep record.exc_info as None
                    logger.warning(
                        "Could not process entry '%s' in '%s': %s. Skipping.",
                        entry_name,
                        directory,
                        entry_error,
                    )
                except Exception:
                    # Log unexpected errors with stack trace
                    logger.exception(
                        "Unexpected error processing entry '%s' in '%s'. Skipping.",
                        entry_name,
                        directory,
                    )
                # --- End of inner try...except ---

    # --- Handle errors during the initial SCANDIR CALL or setup - RAISE ---
    except FileNotFoundError as e:
        msg = "Directory not found during scan"
        logger.error("%s: %s", msg, directory, exc_info=False)  # Log context
        raise ScanDirectoryError(msg, directory, e) from e  # Raise custom exception
    except NotADirectoryError as e:
        msg = "Path is not a directory during scan"
        logger.error("%s: %s", msg, directory, exc_info=False)
        raise ScanDirectoryError(msg, directory, e) from e
    except PermissionError as e:
        msg = "Permission denied during scan setup"
        logger.error("%s: %s", msg, directory, exc_info=False)
        raise ScanDirectoryError(msg, directory, e) from e
    except OSError as e:
        # Catch other OS errors specifically related to scandir setup/iteration
        msg = "OS error during scan setup/iteration"
        logger.error("%s for directory %s: %s", msg, directory, e, exc_info=False)
        raise ScanDirectoryError(msg, directory, e) from e
    except Exception as e:  # Catch-all for truly unexpected errors during scan setup
        msg = "Unexpected error during scan setup/iteration"
        # Log full exception here as it's unexpected
        logger.exception("%s for directory %s", msg, directory)
        raise ScanDirectoryError(msg, directory, e) from e

    # --- Log summary and return on successful scan (even if no files found) ---
    if not gathered_data:
        logger.debug(
            "Successfully scanned directory '%s', but found no regular files.",
            directory,
        )
    else:
        logger.debug(
            "Gathered data for %d regular files in %s", len(gathered_data), directory
        )

    return gathered_data
