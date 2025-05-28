import stat
from pathlib import Path

from datamover.file_functions.fs_mock import FS


class DeleteValidationError(Exception):
    """
    Custom exception for any error occurring during the safe_delete operation,
    encompassing both validation and deletion phases.
    """

    pass


def safe_delete(path: Path, fs: "FS") -> None:
    """
    Safely deletes a file if and only if it is a regular file.

    This function first uses `fs.lstat()` to verify that the given path
    points directly to a regular file (i.e., not a symlink, directory, or other
    special file type). If this validation is successful, it then attempts to
    delete the file using `fs.unlink(path, missing_ok=True)`.

    If `fs.unlink(path, missing_ok=True)` is called and the file is already gone
    (or if `fs.unlink` itself raises FileNotFoundError, which can happen in some
    race conditions even with missing_ok=True, depending on the FS implementation),
    this function treats it as a successful deletion and completes silently.

    Args:
        path: The Path object representing the file to be deleted.
        fs: An FS object providing `lstat` and `unlink` methods.

    Raises:
        DeleteValidationError: This exception is raised for any failure
            encountered during the validation or deletion process, except for
            FileNotFoundError during the unlink phase (which is treated as success).
            Specific reasons for DeleteValidationError include:
            - The path does not exist or is not accessible during validation (`lstat`).
            - The path points to a non-regular file (e.g., directory, symlink).
            - An OS error or other unexpected error occurs during `fs.lstat()`.
            - An error (other than FileNotFoundError, which is treated as success)
              occurs during `fs.unlink()`. This includes OS errors like
              PermissionError or IsADirectoryError, or other unexpected exceptions.
            The original exception, if any, that led to `DeleteValidationError`
            will be available via the `__cause__` attribute.
    """
    # --- Validation ---
    try:
        st = fs.lstat(path)  # st will typically be os.stat_result
    except FileNotFoundError as e:
        raise DeleteValidationError(
            f"Validation failed: file not found at '{path}'."
        ) from e
    except OSError as e:  # Catches most OS-related errors, including PermissionError
        raise DeleteValidationError(
            f"Validation failed: OS error during lstat of '{path}': {e}"
        ) from e
    except Exception as e:  # Catch-all for any other fs.lstat unexpected errors
        raise DeleteValidationError(
            f"Validation failed: Unexpected error during lstat of '{path}': {e}"
        ) from e

    if not stat.S_ISREG(st.st_mode):
        mode_desc = stat.filemode(st.st_mode)  # stat.filemode uses st_mode
        raise DeleteValidationError(
            f"Validation failed: path '{path}' is not a regular file "
            f"(detected: {mode_desc}, mode={oct(st.st_mode)})."
        )

    # --- Deletion ---
    try:
        # missing_ok=True means well-behaved FS implementations won’t raise FileNotFoundError
        # if the file is already gone.
        fs.unlink(path, missing_ok=True)
    except FileNotFoundError:
        # Explicitly treat FileNotFoundError from unlink as success,
        # covering race conditions or non-standard FS behavior.
        return
    except Exception as e:
        # Wrap all other unlink failures (e.g., PermissionError, IsADirectoryError)
        raise DeleteValidationError(
            f"Deletion failed: could not unlink '{path}': {e}"
        ) from e
