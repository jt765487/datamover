import logging
from pathlib import Path

from datamover.file_functions.fs_mock import FS

logger = logging.getLogger(__name__)


def resolve_and_validate_directory(raw_path: Path, fs: FS, dir_label: str) -> Path:
    """
    Resolves a directory path strictly and validates it's a directory using the FS abstraction.

     This is intended for validating critical directory paths during initialization.

    Args:
        raw_path: The Path object to validate (type enforced by static analysis).
        fs: The filesystem abstraction instance.
        dir_label: A descriptive label for the directory (e.g., "source", "work")
                   used in logs/errors.

    Returns:
        The resolved, validated directory Path.

    Raises:
        FileNotFoundError: If the path does not exist (checked via fs.resolve strict=True).
        NotADirectoryError: If the path exists but is not a directory (checked via fs.is_dir).
        TypeError: If an underlying FS operation receives an incompatible type
                   (should be caught by mypy beforehand ideally).
        ValueError: Wraps any other unexpected Exception encountered during FS operations,
                    indicating an unexpected validation failure.
    """
    logger.debug("Validating %s directory path: %s", dir_label, raw_path)

    try:
        # 1. Attempt to resolve strictly (checks existence)
        # If raw_path is not a Path (violating static type), this fs call
        # is likely the first place a runtime TypeError might occur.
        resolved_path: Path = fs.resolve(raw_path, strict=True)

        # 2. Check if it's actually a directory using the FS abstraction
        if not fs.is_dir(resolved_path):
            error_msg = f"{dir_label.capitalize()} path '{resolved_path}' exists but is not a directory (checked via FS)."
            logger.error("Validation Failed: %s", error_msg)  # Log as error, not debug
            raise NotADirectoryError(error_msg)

        logger.debug(
            "Successfully validated %s directory: %s -> %s",
            dir_label,
            raw_path,
            resolved_path,
        )
        return resolved_path

    except FileNotFoundError:
        # Log the specific error before re-raising
        logger.error(
            "Validation Failed: %s directory '%s' not found.", dir_label, raw_path
        )
        raise
    except NotADirectoryError:
        # Error already logged above before raising. Re-raise directly.
        raise
    except TypeError as e:
        # Catch potential TypeErrors from FS methods if type contract violated at runtime
        logger.error(
            "Validation Failed: TypeError during FS operation for %s directory '%s'. %s",
            dir_label,
            raw_path,
            e,  # Include the error message
            exc_info=True,  # Include stack trace for type errors
        )
        # Re-raise TypeError directly; this indicates a programming error/type violation
        raise
    except OSError as e:
        # Catch OS-level errors (PermissionError, etc.) more specifically
        logger.error(
            "Validation Failed: OS error for %s directory '%s': %s",
            dir_label,
            raw_path,
            e,
            exc_info=True,  # Include stack trace for OS errors
        )
        # Wrap in ValueError for consistent handling, preserving cause
        raise ValueError(
            f"OS error validating {dir_label} directory '{raw_path}' using FS"
        ) from e
    except Exception as e:
        # Wrap *other* unexpected FS/OS errors
        logger.error(
            "Validation Failed: Unexpected error for %s directory '%s': %s",
            dir_label,
            raw_path,
            e,
            exc_info=True,  # Include stack trace for unexpected errors
        )
        raise ValueError(
            f"Unexpected error validating {dir_label} directory '{raw_path}' using FS"
        ) from e
