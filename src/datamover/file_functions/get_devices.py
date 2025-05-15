import logging
from pathlib import Path
import os

from datamover.file_functions.fs_mock import FS
from datamover.startup_code.load_config import ConfigError

logger = logging.getLogger(__name__)


def get_device(path: Path, fs: FS) -> int:
    """
    Gets the device ID for the given path using the injected FS object.

    Args:
        path: The path (must be a Path object) to check.
        fs: The filesystem interface object.

    Returns:
        The device ID (st_dev) as an integer.

    Raises:
        ConfigError: If the path does not exist (FileNotFoundError from fs.stat).
                     The original FileNotFoundError is chained as the cause.
        OSError: Propagates other OS errors from fs.stat (e.g., PermissionError).
    """
    try:
        stat_result: os.stat_result = fs.stat(path)
        return stat_result.st_dev
    except FileNotFoundError as e:
        logger.debug("Path not found during stat for device ID: %s", path)
        raise ConfigError(f"[Directories] cannot stat {path}") from e
    except OSError as e:
        logger.warning("OSError during stat for device ID %s: %s", path, e)
        raise  # Re-raise the original OSError
    except Exception:
        logger.exception("Unexpected error getting device ID for %s", path)
        raise
