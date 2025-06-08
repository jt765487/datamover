import logging
import shutil
from pathlib import Path

from datamover.startup_code.load_config import Config, ConfigError

logger = logging.getLogger(__name__)


def _detect_capacity(path: Path) -> int:
    """Gets the total disk capacity for a given path."""
    try:
        stats = shutil.disk_usage(path)
    # Handle cases where the path doesn't exist, or we lack permissions.
    except (FileNotFoundError, OSError) as e:
        # Re-raise as a ValueError to be handled by the calling function.
        raise ValueError(f"Cannot access disk stats for {path!r}") from e

    if stats.total <= 0:
        raise ValueError(f"Detected non-positive capacity ({stats.total}) for path {path!r}")
    return stats.total

def get_effective_disk_capacity(cfg: Config) -> int:
    """
    Determine total disk capacity for the configured base directory.

    Raises:
        ConfigError: If the base directory does not exist or if its disk
                     capacity cannot be determined.
    """
    base_dir = Path(cfg.base_dir)
    logger.info("Checking disk at %r", base_dir)

    if not base_dir.exists():
        raise ConfigError(f"Configured base_dir does not exist: {base_dir!r}")

    try:
        detected = _detect_capacity(base_dir)
        logger.info("Detected capacity: %d bytes", detected)
        return detected
    # Only catch the specific error we expect from our helper.
    except ValueError as err:
        # Chain the exception to preserve the original traceback for debugging.
        raise ConfigError(
            f"Could not determine disk capacity for {base_dir!r}. See cause above."
        ) from err