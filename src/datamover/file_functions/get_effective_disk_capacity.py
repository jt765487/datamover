import logging
import shutil

from datamover.startup_code.load_config import Config, ConfigError

logger = logging.getLogger(__name__)


def get_effective_disk_capacity(cfg: Config) -> int:
    """
    Determines the effective total disk capacity for the purger using cfg.base_dir.

    It prioritizes dynamic detection if the 'purger_total_disk_capacity_bytes'
    setting in the configuration is not a positive integer. It assumes cfg.base_dir
    exists and is accessible, as this should be ensured by prior startup steps
    (e.g., create_directories).

    Args:
        cfg: The application Config object, containing base_dir and purger
             capacity settings.

    Returns:
        The effective total disk capacity in bytes.

    Raises:
        ConfigError: If disk capacity cannot be determined (e.g., dynamic detection fails
                     due to OS errors or inaccessible base_dir, AND no valid positive integer
                     is configured for 'purger_total_disk_capacity_bytes').
    """
    base_dir_for_check = cfg.base_dir
    logger.info(
        "Determining effective disk capacity for purger, using reference path: %s",
        base_dir_for_check
    )

    configured_capacity = cfg.purger_total_disk_capacity_bytes
    effective_total_disk_capacity: int  # Initialize for type hinting, will be set

    # Determine if dynamic detection should be attempted.
    # Attempt if configured_capacity is not explicitly set to a positive integer.
    should_attempt_dynamic_detection = not (
            isinstance(configured_capacity, int) and configured_capacity > 0
    )

    if should_attempt_dynamic_detection:
        logger.info(
            "Configured 'purger_total_disk_capacity_bytes' (%s) is not a positive integer. "
            "Attempting dynamic detection using path: %s",
            configured_capacity, base_dir_for_check
        )
        try:
            # shutil.disk_usage expects a string path.
            # It will raise FileNotFoundError if base_dir_for_check doesn't exist,
            # or OSError for other issues like permissions.
            disk_usage_stats = shutil.disk_usage(str(base_dir_for_check))
            detected_capacity = disk_usage_stats.total

            if detected_capacity <= 0:
                # This is highly unlikely for a valid filesystem path but check defensively.
                raise ValueError(
                    f"Dynamically detected disk capacity for '{base_dir_for_check}' "
                    f"was {detected_capacity}, which is not positive."
                )

            logger.info(
                "Dynamically detected total disk capacity for '%s' as %s bytes.",
                base_dir_for_check, f"{detected_capacity:,}"
            )
            effective_total_disk_capacity = detected_capacity

        except Exception as e:  # Catches FileNotFoundError, OSError, ValueError from above
            logger.error(
                "Dynamic disk capacity detection failed for path '%s'. Error: %s",
                base_dir_for_check, e, exc_info=True
            )
            # Dynamic detection failed, so we MUST fall back to configured_capacity.
            # If configured_capacity is also invalid, then we cannot proceed.
            if isinstance(configured_capacity, int) and configured_capacity > 0:
                logger.warning(
                    "Dynamic detection failed. Falling back to the configured "
                    "'purger_total_disk_capacity_bytes': %s bytes.",
                    f"{configured_capacity:,}"
                )
                effective_total_disk_capacity = configured_capacity
            else:
                # Both dynamic detection failed AND the configured value is unusable.
                raise ConfigError(
                    f"Purger critical: Dynamic disk capacity detection failed for '{base_dir_for_check}' "
                    f"AND the configured 'purger_total_disk_capacity_bytes' ({configured_capacity}) "
                    f"is not a positive integer. Cannot determine disk capacity. Original error: {e}"
                ) from e
    else:
        # Used the configured value because it was a positive integer.
        logger.info(
            "Using pre-configured 'purger_total_disk_capacity_bytes': %s bytes.",
            f"{configured_capacity:,}"
        )
        effective_total_disk_capacity = configured_capacity

    # Final check on the value we ended up with.
    # This should ideally never fail if the logic above is correct, but serves as a safeguard.
    if not (isinstance(effective_total_disk_capacity, int) and effective_total_disk_capacity > 0):
        raise ConfigError(
            f"Purger critical: The final effective total disk capacity is '{effective_total_disk_capacity}', "
            "which is invalid (not a positive integer). This indicates an issue in the "
            "capacity determination logic or configuration."
        )

    logger.info(
        "Effective total disk capacity for purger has been set to: %s bytes.",
        f"{effective_total_disk_capacity:,}"
    )
    return effective_total_disk_capacity