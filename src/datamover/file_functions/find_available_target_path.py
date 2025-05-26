import logging
from pathlib import Path
from typing import Optional

from datamover.file_functions.fs_mock import FS

logger = logging.getLogger(__name__)


def find_available_target_path(
    *,
    base_path: Path,
    limit: int = 100,
    fs: FS,
) -> Optional[Path]:
    """
    Finds an available target path by appending '-N' if variants exist.

    Generates alternative filenames ('file-1.txt', 'file-2.txt', etc.) and
    checks existence using fs.exists(). Returns the first non-existent path,
    or None if limit is reached or errors occur during checks.

    Args:
        base_path: The initial target path to check and base variants on.
        limit: Max number of attempts before giving up.
        fs: The FS object providing the .exists() method. Defaults to real FS.

    Returns:
        A non-existent Path object based on fs.exists(), or None if the limit
        was reached or an OS/other error occurred during an existence check.
    """
    try:
        stem = base_path.stem
        suffix = base_path.suffix
        parent = base_path.parent
    except AttributeError as e:
        # Catch error if base_path wasn't really a Path object
        logger.error("Invalid base_path provided (failed to get parts): %s", e)
        return None

    counter = 1
    while counter <= limit:
        # Construct candidate path, e.g., /parent/stem-1.suffix
        candidate = parent / f"{stem}-{counter}{suffix}"
        try:
            path_exists = fs.exists(candidate)
            if not path_exists:
                logger.debug(
                    "Found available path '%s' for base '%s' after %d attempt(s).",
                    candidate,
                    base_path.name,
                    counter,
                )
                return candidate  # Found available path

        except OSError as e_os:
            logger.error(
                "OSError checking existence for candidate path '%s' (derived from '%s'): %s. Aborting search.",
                candidate,
                base_path.name,
                e_os,
            )
            return None  # Abort search on OS error
        except Exception:
            logger.exception(
                "Unexpected error checking existence for candidate path '%s' (derived from '%s'). Aborting search.",
                candidate,
                base_path.name,
            )
            return None  # Abort search on other errors

        # If path_exists was True, log minimally on first conflict and continue
        if counter == 1:
            logger.debug("Path '%s' exists, attempting next candidate.", candidate)

        counter += 1

    # --- Loop finished: Limit Reached ---
    logger.error(
        "Could not find available path for base '%s' within limit of %d attempts.",
        base_path.name,
        limit,
    )
    return None  # Limit reached
