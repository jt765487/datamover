import logging
from pathlib import Path

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.get_devices import get_device
from datamover.startup_code.load_config import ConfigError, Config

logger = logging.getLogger(__name__)


def create_directories(cfg: Config, fs: FS) -> None:  # <-- Inject fs: FS
    """
    Validates and ensures the application's core directory structure using
    an injected FS object for all filesystem interactions.

    Ensures `base_dir` exists and is a directory. Creates other required dirs
    if missing. Validates all required dirs are on the same device as `base_dir`.

    Args:
        cfg: The application Config object (assumed typed correctly).
        fs: The filesystem abstraction object. # <-- Updated dependency

    Raises:
        ConfigError: For configuration issues, invalid paths, creation failures,
                     device mismatches, or underlying OS/Type errors.
        AttributeError: If expected directory attributes are missing from cfg.
    """
    logger.info("Validating and ensuring application directory structure...")

    # --- Gather Paths ---
    try:
        base_dir = cfg.base_dir
        paths_to_process: set[Path] = {
            base_dir,
            cfg.source_dir,
            cfg.worker_dir,
            cfg.uploaded_dir,
            cfg.dead_letter_dir,
            cfg.csv_dir,
        }
    except AttributeError as e:
        raise ConfigError(
            f"Config object missing required directory attribute: {e}"
        ) from e

    # --- 1. Validate Base Directory ---
    base_dev: int
    logger.debug("Validating base directory: %s", base_dir)
    try:
        # get_device checks existence implicitly via fs.stat
        base_dev = get_device(base_dir, fs=fs)
        if not fs.is_dir(base_dir):  # Use fs.is_dir directly
            raise ConfigError(f"Base path '{base_dir}' exists but is not a directory.")
        logger.info(
            "Base directory '%s' validated successfully on device %d.",
            base_dir,
            base_dev,
        )
    # Catch errors from get_device (which wraps ConfigError)
    except ConfigError as e:
        msg = f"Base directory '{base_dir}' is invalid or inaccessible: {e}"
        logger.critical("CRITICAL: %s", msg)
        raise  # Re-raise ConfigError
    # Catch direct OS errors from fs.is_dir or underlying fs.stat
    except (OSError, TypeError) as e:
        msg = f"Error validating base directory '{base_dir}': {e}"
        logger.critical("CRITICAL: %s", msg)
        raise ConfigError(msg) from e
    except Exception as e_base:
        msg = f"Unexpected error validating base directory '{base_dir}'"
        logger.critical("CRITICAL: %s: %s", msg, e_base)
        raise ConfigError(msg) from e_base

    # --- 2. Ensure Other Directories Exist on Correct Device ---
    sorted_paths = sorted(list(paths_to_process))

    for path in sorted_paths:
        if path == base_dir:
            continue

        logger.debug("Processing required path: %s", path)
        try:
            path_exists = fs.exists(path)

            if path_exists:
                if not fs.is_dir(path):
                    raise ConfigError(
                        f"Required path '{path}' exists but is not a directory."
                    )
                logger.debug("Directory '%s' already exists.", path)
            else:
                # Create directory using fs.mkdir (requires exist_ok=True)
                logger.info("Attempting creation of directory '%s' via FS...", path)
                fs.mkdir(path, exist_ok=True)
                logger.info("Successfully ensured directory '%s' exists via FS.", path)

            # Get device ID by calling get_device with injected fs
            current_dev = get_device(path, fs=fs)

            # Compare device ID
            if current_dev != base_dev:
                raise ConfigError(
                    f"Directory '{path}' (device {current_dev}) is not on the same filesystem as base directory '{base_dir}' (device {base_dev})."
                )

            logger.debug("Directory '%s' validated on device %d.", path, current_dev)

        except ConfigError:  # Re-raise specific ConfigErrors from this loop's logic
            raise
        # Catch direct OS/Type errors from fs calls or get_device
        except (OSError, TypeError) as e_path:
            msg = f"Error accessing or processing path '{path}': {e_path}"
            logger.critical("CRITICAL: %s", msg)
            raise ConfigError(msg) from e_path
        except Exception as e_unexpected:  # Catch other errors
            msg = f"Unexpected error processing path '{path}'"
            logger.critical("CRITICAL: %s: %s", msg, e_unexpected)
            raise ConfigError(msg) from e_unexpected

    logger.info(
        "All required application directories validated successfully on device %d.",
        base_dev,
    )
