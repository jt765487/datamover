import logging
from pathlib import Path
from typing import Optional

from datamover.file_functions.determin_destination import determine_destination
from datamover.file_functions.fs_mock import FS
from datamover.file_functions.validate_file import validate_file
from datamover.file_functions.safe_stat import safe_stat
from datamover.file_functions.execute_move_file import execute_move_file

logger = logging.getLogger(__name__)


class MoveValidationError(Exception):
    """
    Custom exception raised when any validation or pre-move check fails
    within the move_file_safely_impl workflow. It carries a descriptive
    message indicating the cause of the failure.
    """

    pass


def _basic_resolve_source(source_path_raw: Path, fs: FS) -> Path:
    """
    Performs basic existence and resolution checks on the source path.

    It first uses `safe_stat` to verify that the file can be stat-ed (implying
    existence and accessibility). If successful, it then uses `fs.resolve(strict=True)`
    to obtain a canonical, strictly resolved Path object.

    Args:
        source_path_raw: The raw source path to check and resolve.
        fs: The filesystem abstraction instance.

    Returns:
        A resolved Path object for the source file.

    Raises:
        MoveValidationError: If `safe_stat` fails (e.g., file not found,
                             permission error, logged by `safe_stat` itself),
                             or if `fs.resolve` fails (e.g., file not found
                             during resolution, symbolic link issues, OS errors).
                             The exception message will detail the cause.
    """
    # safe_stat logs its own specific errors if it returns None
    stat_info = safe_stat(path=source_path_raw, fs=fs)
    if stat_info is None:
        # safe_stat would have logged. This exception provides context for move_file_safely_impl.
        raise MoveValidationError(
            f"Basic source check (safe_stat) failed for '{source_path_raw}'. See previous logs from safe_stat."
        )

    try:
        resolved_path = fs.resolve(source_path_raw, strict=True)
        return resolved_path
    except FileNotFoundError as e:
        raise MoveValidationError(
            f"Source '{source_path_raw}' not found during path resolution: {e}"
        )
    except TypeError as e:  # Less common if Path() was used in safe_stat, but good for fs.resolve robustness
        raise MoveValidationError(
            f"Invalid source path type for resolution of '{source_path_raw}': {e}"
        )
    except OSError as e:  # Other OS-level errors during resolution
        raise MoveValidationError(
            f"OS error during path resolution of '{source_path_raw}': {e}"
        )
    except Exception as e:  # Catch-all for unexpected fs.resolve issues
        raise MoveValidationError(
            f"Unexpected error during path resolution of '{source_path_raw}': {e}"
        )


def _determine_final_destination(
    resolved_source_path: Path, destination_dir: Path, fs: FS
) -> Path:
    """
    Determines a non-conflicting final destination path for the source file
    within the given destination directory.

    It constructs an initial candidate path by joining `destination_dir` with
    the `resolved_source_path.name`. It then delegates to the
    `determine_destination` helper function to handle potential naming
    conflicts and find a unique final path.

    Args:
        resolved_source_path: The resolved Path object of the source file.
        destination_dir: The resolved Path object of the target directory.
        fs: The filesystem abstraction instance.

    Returns:
        A resolved Path object for the final, non-conflicting destination.

    Raises:
        MoveValidationError: If `determine_destination` fails to find a valid
                             final path (e.g., due to too many conflicts or
                             other logic within `determine_destination`).
                             `determine_destination` is expected to log specifics.
    """
    initial_dest_path = destination_dir / resolved_source_path.name
    final_dest_path = determine_destination(
        initial_dest_path=initial_dest_path,
        source_name_for_log=resolved_source_path.name,  # Or str(resolved_source_path)
        fs=fs,
    )
    if final_dest_path is None:
        # determine_destination would have logged the specific reason.
        raise MoveValidationError(
            f"Could not determine a valid final destination for '{resolved_source_path.name}' in '{destination_dir}'. "
            "See previous logs from determine_destination."
        )
    return final_dest_path


def move_file_safely_impl(
    source_path_raw: Path,  # Changed name for consistency
    destination_dir: Path,  # Changed name for consistency
    fs: FS,
    expected_source_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Safely moves a file from `source_path_raw` into `destination_dir`.

    This function orchestrates the file move process with several safety checks:
      1. Source Validation:
         - If `expected_source_dir` is provided, `validate_file` performs full
           validation (existence, type, confinement within `expected_source_dir`,
           and resolution).
         - Otherwise, `_basic_resolve_source` performs basic checks (existence via
           `safe_stat` and strict resolution via `fs.resolve`).
      2. Destination Determination: `_determine_final_destination` calculates a
         non-conflicting path in the `destination_dir`.
      3. Execution: `execute_move_file` performs the actual filesystem move.

    Failures in any of these steps will result in the move being aborted.
    This function uses an internal `MoveValidationError` to handle pre-move
    failures, logging them and returning None.

    Args:
        source_path_raw: The raw, unverified source file Path.
        destination_dir: The existing, resolved target directory Path.
        fs: A filesystem abstraction instance for all file operations.
        expected_source_dir: Optional. If provided, the source file must be
                             validated to exist within this directory.

    Returns:
        The resolved final destination Path of the moved file on success.
        None if any step of the validation, destination determination, or
        move execution fails.

    Logs:
        - INFO: On successful completion of the move, detailing source and destination.
        - ERROR: If the move is aborted due to validation, destination determination,
                 or execution failure. The log message will include the content of
                 the raised `MoveValidationError` or a generic message for
                 `execute_move_file` failures. Helper functions (`validate_file`,
                 `safe_stat`, `determine_destination`, `execute_move_file`) are
                 expected to log more specific details of their failures.
        - EXCEPTION: For any unexpected errors not caught as `MoveValidationError`.
    """
    try:
        # --- 1. Validate or Resolve Source Path ---
        resolved_source_path: Path  # Type hint for clarity
        if expected_source_dir is not None:
            # Full validation (includes resolution)
            validated_path = validate_file(
                source_path_input=source_path_raw,
                expected_source_dir=expected_source_dir,
                fs=fs,
            )
            if validated_path is None:
                # Validate_file logs specifics. This exception gives context to move_file_safely_impl's log.
                raise MoveValidationError(
                    f"Full validation failed for '{source_path_raw}'. "
                    "See previous logs from validate_file for details."
                )
            resolved_source_path = validated_path
        else:
            # Basic checks (stat and strict resolution)
            resolved_source_path = _basic_resolve_source(source_path_raw, fs)

        # --- 2. Determine Final Destination Path ---
        final_dest_path = _determine_final_destination(
            resolved_source_path, destination_dir, fs
        )

        # --- 3. Execute Move ---
        move_success = execute_move_file(
            resolved_source_path=resolved_source_path,
            final_dest_path=final_dest_path,
            fs=fs,
        )
        if not move_success:
            # execute_move_file logs specifics.
            raise MoveValidationError(
                f"File move execution failed for '{resolved_source_path}' to '{final_dest_path}'. "
                "See previous logs from execute_move_file for details."
            )

        # --- 4. Success ---
        logger.debug(
            "Successfully moved '%s' to '%s'", resolved_source_path, final_dest_path
        )
        return final_dest_path

    except MoveValidationError as e:
        logger.error(
            "Move aborted for '%s': %s",
            source_path_raw,  # Log the original raw path for user context
            e,  # The descriptive message from MoveValidationError
        )
        return None
    except Exception as e:
        # Catch-all for truly unexpected errors not handled by the above.
        logger.exception(
            "Unexpected critical error during move process for '%s': %s",
            source_path_raw,
            e,
        )
        return None
