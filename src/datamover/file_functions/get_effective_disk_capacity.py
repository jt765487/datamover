import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class DiskCapacityError(ValueError):  # Custom exception for clarity
    """Raised when disk capacity cannot be determined or is invalid."""
    pass


def get_disk_capacity_for_path(path: Path) -> int:
    """
    Gets the total disk capacity for the filesystem containing the given path.

    Args:
        path: A Path object on the filesystem whose capacity is to be determined.

    Returns:
        The total disk capacity in bytes.

    Raises:
        DiskCapacityError: If disk stats cannot be accessed, or if the
                           detected capacity is non-positive.
    """
    if not isinstance(path, Path):
        # This check is good practice, though type hints help catch it earlier.
        raise TypeError(f"Expected a Path object for capacity detection, got {type(path)}.")

    logger.debug("Attempting to get disk usage for path: %s", path)
    try:
        stats = shutil.disk_usage(path)
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error("Failed to get disk usage for '%s': %s", path, e)
        raise DiskCapacityError(
            f"Cannot determine disk capacity for {path!r}. OS error: {e}"
        ) from e

    if stats.total <= 0:
        logger.error(
            "Detected non-positive disk capacity (%d) for path '%s'", stats.total, path
        )
        raise DiskCapacityError(
            f"Detected non-positive capacity ({stats.total}) for path {path!r}"
        )

    logger.debug("Successfully determined disk capacity for '%s': %d bytes", path, stats.total)

    return stats.total
