import logging
import os
import stat
import time
from pathlib import Path
from typing import Optional, Union
from unittest.mock import Mock, MagicMock

import pytest

from datamover.file_functions.fs_mock import FS

logger = logging.getLogger(__name__)


def configure_mock_stat_behavior(
    mock_method_to_configure: Mock,
    path_to_result_map: dict[
        Path,
        Union[os.stat_result, Exception],  # More specific than 'object' if only these two
    ],
):
    """
    Configures a mock method (like fs.stat, fs.lstat, etc.)
    using a side_effect based on an input path.

    Args:
        mock_method_to_configure: The mock method (e.g., mock_fs.stat).
        path_to_result_map: A dictionary mapping Path objects to their
                             expected return values (os.stat_result) or
                             exceptions to be raised.
    """

    def side_effect_logic(p: Path):
        path_key = Path(p)  # Ensure p is treated as a Path for dictionary lookup
        if path_key in path_to_result_map:
            result = path_to_result_map[path_key]
            if isinstance(result, Exception):
                raise result
            # Assuming it's os.stat_result if not an Exception, based on type hint
            return result
        else:
            # Using _extract_mock_name() is okay for unittest.mock, might be internal
            # but generally works.
            mock_name = (
                mock_method_to_configure._extract_mock_name()
                if hasattr(mock_method_to_configure, "_extract_mock_name")
                else str(mock_method_to_configure)
            )
            raise KeyError(
                f"Path '{path_key}' not found in mock configuration for {mock_name}."
            )

    mock_method_to_configure.side_effect = side_effect_logic


def create_mock_dir_stat_result(
    dev: int, mode: int = stat.S_IFDIR | 0o755
) -> MagicMock:  # Returns MagicMock spec'd to os.stat_result
    """
    Creates a mock os.stat_result object, typically configured as a directory.
    Useful for tests involving directory existence and device checks.
    """
    res = MagicMock(spec=os.stat_result)
    res.st_dev = dev
    res.st_mode = mode
    res.st_ino = 0  # Default, can be customized if a test needs specific inode
    res.st_nlink = 1  # Typical for a directory (itself)
    res.st_uid = os.geteuid() if hasattr(os, "geteuid") else 0
    res.st_gid = os.getegid() if hasattr(os, "getegid") else 0
    res.st_size = 4096  # A common default size for a directory block

    # Consistent, predictable timestamp default for mocks
    default_time = time.time()
    res.st_atime = default_time
    res.st_mtime = default_time
    res.st_ctime = default_time
    return res


def create_mock_stat_attrs(
    st_mode: int = stat.S_IFREG | 0o644,
    st_ino: int = 1,
    st_size: int = 1024,
    st_dev: int = 10,
    st_nlink: int = 1,
    st_uid: Optional[int] = None,  # Allow None to use sensible defaults
    st_gid: Optional[int] = None,  # Allow None to use sensible defaults
    st_atime: Optional[float] = None,
    st_mtime: Optional[float] = None,
    st_ctime: Optional[float] = None,
) -> MagicMock:  # Returns MagicMock spec'd to os.stat_result
    """
    Creates a MagicMock object simulating os.stat_result with configurable attributes.
    Defaults to simulating a regular file.
    """
    res = MagicMock(spec=os.stat_result)
    res.st_mode = st_mode
    res.st_ino = st_ino
    res.st_size = st_size
    res.st_dev = st_dev
    res.st_nlink = st_nlink

    res.st_uid = (
        st_uid
        if st_uid is not None
        else (os.geteuid() if hasattr(os, "geteuid") else 0)
    )
    res.st_gid = (
        st_gid
        if st_gid is not None
        else (os.getegid() if hasattr(os, "getegid") else 0)
    )

    default_timestamp = time.time()
    res.st_atime = st_atime if st_atime is not None else default_timestamp
    res.st_mtime = st_mtime if st_mtime is not None else default_timestamp
    res.st_ctime = st_ctime if st_ctime is not None else default_timestamp

    return res


def make_file_entry(name: str, base_dir: Path, stat_result: MagicMock) -> MagicMock:
    """
    Creates a DirEntry mock that represents a regular file.
    - entry.is_file(follow_symlinks=False) returns True.
    - entry.stat(follow_symlinks=False) returns the provided stat_result.
    """
    entry = MagicMock(spec=os.DirEntry)
    entry.name = name
    entry.path = str(base_dir / name)  # os.DirEntry.path is str

    # Configure is_file specifically for follow_symlinks=False
    # If called with True, it would return a new MagicMock by default.
    entry.is_file = Mock(return_value=True)  # Default for any args
    entry.is_file.configure_mock(
        **{
            "return_value": True,
            "side_effect": lambda follow_symlinks=False: True
            if not follow_symlinks
            else Mock(),
        }
    )

    def is_file_logic(follow_symlinks: bool = False) -> bool:
        if not follow_symlinks:
            return True
        # To be more robust, if follow_symlinks=True is ever called,
        # it should behave as a mock (or raise if unexpected)
        # For this SUT, only follow_symlinks=False is used.
        raise AssertionError("is_file called with follow_symlinks=True unexpectedly")

    entry.is_file = Mock(side_effect=is_file_logic)

    # Configure stat specifically for follow_symlinks=False
    def stat_logic(follow_symlinks: bool = False) -> MagicMock:
        if not follow_symlinks:
            return stat_result
        raise AssertionError("stat called with follow_symlinks=True unexpectedly")

    entry.stat = Mock(side_effect=stat_logic)

    # Ensure other type checks (is_dir, is_symlink) return False if called
    entry.is_dir = Mock(return_value=False)
    entry.is_symlink = Mock(return_value=False)
    return entry


def make_nonfile_entry(
    name: str, base_dir: Path, is_dir: bool = False, is_symlink: bool = False
) -> MagicMock:
    """
    Creates a DirEntry mock that represents a non-regular-file (e.g., dir, symlink).
    - entry.is_file(follow_symlinks=False) returns False.
    """
    entry = MagicMock(spec=os.DirEntry)
    entry.name = name
    entry.path = str(base_dir / name)

    def is_file_logic_nonfile(follow_symlinks: bool = False) -> bool:
        # For non-files, is_file should be False regardless of follow_symlinks
        # in the context of this SUT (which calls it with follow_symlinks=False)
        if not follow_symlinks:
            return False
        raise AssertionError(
            "is_file called with follow_symlinks=True unexpectedly on non-file entry"
        )

    entry.is_file = Mock(side_effect=is_file_logic_nonfile)

    entry.is_dir = Mock(return_value=is_dir)
    entry.is_symlink = Mock(return_value=is_symlink)

    # stat() should not be called by gather_file_data if is_file returns False.
    entry.stat = Mock(
        side_effect=AssertionError(
            f"stat() should not be called on non-file entry '{name}' by SUT path"
        )
    )
    return entry


class SetupError(Exception):  # Renamed from TestSetupError
    """Indicates an error during test file/directory setup."""

    pass


def create_and_stamp_real_fs(
    fs_operations: FS,
    full_path: Path,
    size: int,
    mtime: float,
    initial_create: bool = True,
):
    """Create or resize a file, set its mtime, and verify setup."""
    # Using a logger specific to this function for clarity
    func_logger = logging.getLogger(f"{__name__}.create_and_stamp_real_fs")
    parent_dir = full_path.parent
    if not fs_operations.exists(parent_dir):
        func_logger.debug("Creating parent directory: %s", parent_dir)
        fs_operations.mkdir(parent_dir, exist_ok=True)

    file_exists = fs_operations.exists(full_path)

    if initial_create or not file_exists:
        func_logger.debug(
            "Creating file (initial_create=%s, exists=%s): %s",
            initial_create,
            file_exists,
            full_path,
        )
        with fs_operations.open(full_path, "wb") as f:
            if size > 0:
                f.write(b"\0" * size)
    elif (
        file_exists
    ):  # File exists and initial_create is False, potentially modify size
        current_stat = fs_operations.stat(full_path)
        if current_stat.st_size != size:
            func_logger.debug(
                "Resizing existing file from %s to %s: %s",
                current_stat.st_size,
                size,
                full_path,
            )
            with fs_operations.open(full_path, "wb") as f:  # Overwrite to resize
                if size > 0:
                    f.write(b"\0" * size)

    try:
        func_logger.debug("Setting mtime to %s for %s", mtime, full_path)
        os.utime(str(full_path), (mtime, mtime))
    except Exception as e:
        func_logger.error("Failed to set mtime for %s: %s", full_path, e)
        raise  # Re-raise original exception, or wrap if preferred

    # Verification step
    final_stat = fs_operations.stat(full_path)
    if final_stat.st_size != size:
        msg = (
            f"File size mismatch after setup for {full_path}. "
            f"Expected {size}, got {final_stat.st_size}"
        )
        func_logger.error(msg)
        raise SetupError(msg)  # Use the defined SetupError
    if not pytest.approx(final_stat.st_mtime, abs=1) == mtime:
        msg = (
            f"File mtime mismatch after setup for {full_path}. "
            f"Expected ~{mtime}, got {final_stat.st_mtime}"
        )
        func_logger.error(msg)
        raise SetupError(msg)
