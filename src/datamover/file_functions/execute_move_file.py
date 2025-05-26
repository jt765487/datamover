import logging
from pathlib import Path

from datamover.file_functions.fs_mock import FS

logger = logging.getLogger(__name__)


def execute_move_file(
    resolved_source_path: Path,
    final_dest_path: Path,
    fs: FS,
) -> bool:
    """
    Performs the file move using injected FS.move with error handling.

    Treats FileNotFoundError during move as non-fatal (idempotency).

    Args:
        resolved_source_path: The source path (assumed resolved).
        final_dest_path: The destination path.
        fs: Filesystem operations provider (dependency must be injected).

    Returns:
        True if the move succeeded or the source was already gone.
        False if an error (PermissionError, OSError, etc.) occurred.
    """
    try:
        logger.debug(
            "Executing move via FS: '%s' -> '%s'", resolved_source_path, final_dest_path
        )
        fs.move(resolved_source_path, final_dest_path)
        return True

    except FileNotFoundError:
        # Treat source not found during fs.move attempt as acceptable
        logger.warning(
            "Source file '%s' does not exist during FS.move attempt to '%s'. Considered successful.",
            resolved_source_path,
            final_dest_path,
        )
        return True  # Considered success/idempotent
    except PermissionError as e:
        logger.error(
            "PermissionError during FS.move '%s' to '%s': %s",
            resolved_source_path,
            final_dest_path,
            e,
        )
        return False
    except OSError as e:
        # Catch other OS errors raised by fs.move
        logger.error(
            "OSError during FS.move '%s' to '%s': %s",
            resolved_source_path,
            final_dest_path,
            e,
        )
        return False
    except Exception:
        # Catch unexpected errors from fs.move
        logger.exception(
            "Unexpected error during FS.move '%s' to '%s'",
            resolved_source_path,
            final_dest_path,
        )
        return False
