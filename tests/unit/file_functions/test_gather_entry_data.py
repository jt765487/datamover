import logging
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from datamover.file_functions.file_exceptions import ScanDirectoryError

from datamover.file_functions.gather_entry_data import (
    gather_file_data,
    GatheredEntryData,
)


def create_mock_stat_attrs(
    st_mtime: float, st_size: int, st_mode: int = stat.S_IFREG | 0o644
) -> MagicMock:
    """Creates a MagicMock simulating os.stat_result."""
    res = MagicMock(spec=os.stat_result)
    res.st_mtime = st_mtime
    res.st_size = st_size
    res.st_mode = st_mode
    # Add other attributes if your SUT or helpers use them (st_dev, st_ino, etc.)
    res.st_dev = 1
    res.st_ino = hash(st_mtime)  # just need some value
    return res


def make_mock_dir_entry(
    name: str,
    base_path: Path,
    is_file_result: bool = True,
    is_dir_result: bool = False,  # Added is_dir_result
    is_symlink_result: bool = False,  # Added is_symlink_result
    stat_result: os.stat_result | None = None,
    side_effect_is_file: Exception | None = None,
    side_effect_stat: Exception | None = None,
) -> MagicMock:
    """Creates a mock os.DirEntry object."""
    entry = MagicMock(spec=os.DirEntry)
    entry.name = name
    entry.path = str(base_path / name)

    if side_effect_is_file:
        entry.is_file = MagicMock(side_effect=side_effect_is_file)
    else:
        entry.is_file = MagicMock(return_value=is_file_result)

    # Configure is_dir and is_symlink based on new parameters
    entry.is_dir = MagicMock(return_value=is_dir_result)
    entry.is_symlink = MagicMock(return_value=is_symlink_result)

    if side_effect_stat:
        entry.stat = MagicMock(side_effect=side_effect_stat)
    elif (
        stat_result is not None
    ):  # CRITICAL FIX: Check if stat_result is actually provided
        entry.stat = MagicMock(return_value=stat_result)
    else:
        # Fallback if no specific stat_result or error is provided
        # This was causing issues if stat_result was intended but not used.
        entry.stat = MagicMock(
            return_value=create_mock_stat_attrs(st_mtime=0.0, st_size=0)
        )  # Default fallback
    return entry


# --- Fixtures ---


@pytest.fixture
def scan_dir(tmp_path: Path) -> Path:
    """Provides a concrete directory path for tests that might need it.
    For unit tests of gather_file_data, fs.scandir is usually mocked,
    so this path serves as an argument to the function.
    """
    d = tmp_path / "test_scan_directory"
    d.mkdir(exist_ok=True)
    return d


# --- Tests for gather_file_data ---


def test_gather_empty_directory(scan_dir: Path, mock_fs: MagicMock):
    """Test scanning an empty directory."""
    # Arrange
    mock_fs.scandir.return_value.__enter__.return_value = iter([])  # Empty iterator

    # Act
    result = gather_file_data(scan_dir, mock_fs)

    # Assert
    assert result == []
    mock_fs.scandir.assert_called_once_with(scan_dir)


def test_gather_only_regular_files(scan_dir: Path, mock_fs: MagicMock):
    """Test gathering data from a directory with only regular files."""
    # Arrange
    file1_stat = create_mock_stat_attrs(st_mtime=100.0, st_size=1024)
    file2_stat = create_mock_stat_attrs(st_mtime=200.0, st_size=2048)

    entry1 = make_mock_dir_entry("file1.txt", scan_dir, stat_result=file1_stat)
    entry2 = make_mock_dir_entry("file2.dat", scan_dir, stat_result=file2_stat)

    mock_fs.scandir.return_value.__enter__.return_value = iter([entry1, entry2])

    # Mock fs.resolve to return a predictable path
    # (entry.path is str, fs.resolve expects PathLike)
    resolved_path1 = scan_dir / "resolved_file1.txt"
    resolved_path2 = scan_dir / "resolved_file2.dat"
    mock_fs.resolve.side_effect = (
        lambda p, strict: resolved_path1
        if Path(p).name == "file1.txt"
        else resolved_path2
    )

    # Act
    result = gather_file_data(scan_dir, mock_fs)

    # Assert
    assert len(result) == 2
    expected_data = [
        GatheredEntryData(mtime=100.0, size=1024, path=resolved_path1),
        GatheredEntryData(mtime=200.0, size=2048, path=resolved_path2),
    ]
    # Order might not be guaranteed by scandir, so compare sets or sort
    assert sorted(result) == sorted(expected_data)

    entry1.is_file.assert_called_once_with(follow_symlinks=False)
    entry1.stat.assert_called_once_with(follow_symlinks=False)
    entry2.is_file.assert_called_once_with(follow_symlinks=False)
    entry2.stat.assert_called_once_with(follow_symlinks=False)

    mock_fs.resolve.assert_has_calls(
        [
            call(Path(entry1.path), strict=False),
            call(Path(entry2.path), strict=False),
        ],
        any_order=True,
    )


def test_gather_mixed_entries(scan_dir: Path, mock_fs: MagicMock):
    """Test that only regular files are processed, others are skipped."""
    # Arrange
    file_stat = create_mock_stat_attrs(st_mtime=100.0, st_size=1024)
    file_entry = make_mock_dir_entry("real_file.txt", scan_dir, stat_result=file_stat)
    dir_entry = make_mock_dir_entry(
        "subdir", scan_dir, is_file_result=False, is_dir_result=True
    )
    symlink_entry = make_mock_dir_entry(
        "link.txt", scan_dir, is_file_result=False, is_symlink_result=True
    )  # is_file(follow_symlinks=False) would be false for a link itself

    mock_fs.scandir.return_value.__enter__.return_value = iter(
        [file_entry, dir_entry, symlink_entry]
    )
    resolved_file_path = scan_dir / "resolved_real_file.txt"
    mock_fs.resolve.return_value = resolved_file_path

    # Act
    result = gather_file_data(scan_dir, mock_fs)

    # Assert
    assert len(result) == 1
    assert result[0] == GatheredEntryData(
        mtime=100.0, size=1024, path=resolved_file_path
    )

    file_entry.is_file.assert_called_once_with(follow_symlinks=False)
    file_entry.stat.assert_called_once_with(follow_symlinks=False)
    mock_fs.resolve.assert_called_once_with(Path(file_entry.path), strict=False)

    dir_entry.is_file.assert_called_once_with(follow_symlinks=False)
    dir_entry.stat.assert_not_called()  # Should not be called if not a file

    symlink_entry.is_file.assert_called_once_with(follow_symlinks=False)
    symlink_entry.stat.assert_not_called()  # Should not be called if not a file


# --- Tests for fs.scandir raising errors ---
@pytest.mark.parametrize(
    "error_type, error_msg_snippet",
    [
        (FileNotFoundError, "Directory not found during scan"),
        (NotADirectoryError, "Path is not a directory during scan"),
        (PermissionError, "Permission denied during scan setup"),
        (OSError, "OS error during scan setup/iteration"),  # Generic OSError
        (
            RuntimeError,
            "Unexpected error during scan setup/iteration",
        ),  # Other Exception
    ],
)
def test_scandir_initialization_errors(
    scan_dir: Path,
    mock_fs: MagicMock,
    error_type: type[Exception],
    error_msg_snippet: str,
):
    """Test that errors from fs.scandir() call are wrapped in ScanDirectoryError."""
    # Arrange
    original_error = error_type("Original scandir error")
    mock_fs.scandir.side_effect = original_error

    # Act & Assert
    with pytest.raises(ScanDirectoryError, match=error_msg_snippet) as exc_info:
        gather_file_data(scan_dir, mock_fs)

    assert exc_info.value.directory == scan_dir
    assert exc_info.value.__cause__ is original_error


@pytest.fixture
def mock_entry_one(scan_dir: Path) -> MagicMock:
    """A valid file entry."""
    stat_res = create_mock_stat_attrs(100.0, 10)
    return make_mock_dir_entry("file1.txt", scan_dir, stat_result=stat_res)


@pytest.fixture
def mock_entry_two_problematic(scan_dir: Path) -> MagicMock:
    """An entry that will be configured to cause problems."""
    # Basic stat for cases where stat() itself isn't the problem
    stat_res = create_mock_stat_attrs(200.0, 20)
    return make_mock_dir_entry("problem.txt", scan_dir, stat_result=stat_res)


@pytest.fixture
def mock_entry_three(scan_dir: Path) -> MagicMock:
    """Another valid file entry."""
    stat_res = create_mock_stat_attrs(300.0, 30)
    return make_mock_dir_entry("file3.txt", scan_dir, stat_result=stat_res)


@pytest.mark.parametrize("error_stage", ["is_file", "stat", "resolve"])
@pytest.mark.parametrize(
    "exception_type, expected_log_level, log_msg_substring_key, expect_exc_info",
    [
        (
            OSError("Permission Denied on entry"),
            logging.WARNING,
            "Could not process entry",
            False,
        ),
        (
            ValueError("Bad Value on entry"),
            logging.ERROR,
            "Unexpected error processing entry",
            True,
        ),
    ],
    ids=["OSError_on_entry", "ValueError_on_entry"],
)
def test_entry_errors_are_logged_and_skipped(
    scan_dir: Path,  # Fixture
    mock_fs: MagicMock,  # Fixture from conftest.py
    caplog: pytest.LogCaptureFixture,  # Fixture
    mock_entry_one: MagicMock,  # Fixture
    mock_entry_two_problematic: MagicMock,  # Fixture
    mock_entry_three: MagicMock,  # Fixture
    error_stage: str,  # Parametrized
    exception_type: Exception,  # Parametrized
    expected_log_level: int,  # Parametrized
    log_msg_substring_key: str,  # Parametrized
    expect_exc_info: bool,  # Parametrized
):
    """
    Tests that if an error occurs while processing a single DirEntry,
    it's logged, and processing continues for other entries.
    """
    # --- Arrange ---

    # Configure the problematic entry (mock_entry_two_problematic)
    if error_stage == "is_file":
        # Error when calling entry.is_file()
        mock_entry_two_problematic.is_file = MagicMock(side_effect=exception_type)
    elif error_stage == "stat":
        # entry.is_file() succeeds, but entry.stat() fails
        mock_entry_two_problematic.is_file.return_value = True
        mock_entry_two_problematic.stat = MagicMock(side_effect=exception_type)
    elif error_stage == "resolve":
        # entry.is_file() and entry.stat() succeed, but fs.resolve() fails for this entry's path
        mock_entry_two_problematic.is_file.return_value = True
        # Ensure stat provides some valid data if it's called before resolve fails
        mock_entry_two_problematic.stat.return_value = create_mock_stat_attrs(
            st_mtime=222.0, st_size=22
        )

        # This is the CRITICAL FIX: The side_effect for resolve must RAISE the exception.
        def resolve_side_effect_for_test(p: Path, strict: bool):
            if p == Path(mock_entry_two_problematic.path):
                raise exception_type  # RAISE the error for the problematic path
            # For other paths, resolve normally (simplified for test)
            return scan_dir / p.name

        mock_fs.resolve.side_effect = resolve_side_effect_for_test
    else:
        raise ValueError(f"Unknown error_stage: {error_stage}")

    # Set up fs.scandir to yield the mock entries
    mock_fs.scandir.return_value.__enter__.return_value = iter(
        [mock_entry_one, mock_entry_two_problematic, mock_entry_three]
    )

    # Default fs.resolve behavior IF NOT testing "resolve" error stage
    # (because for "resolve" stage, the specific side_effect above handles all cases)
    if error_stage != "resolve":

        def default_resolve_normal_paths(p: Path, strict: bool):
            return scan_dir / p.name  # Simplified resolution for good entries

        mock_fs.resolve.side_effect = default_resolve_normal_paths

    # --- Act ---
    with caplog.at_level(logging.DEBUG):  # Capture all logs from DEBUG upwards
        result = gather_file_data(scan_dir, mock_fs)

    # --- Assert ---
    # Problematic entry should be skipped, so only 2 valid entries should be in the result
    assert len(result) == 2, "Problematic entry was not skipped"

    # Check that the two valid entries are present and correctly processed
    # (Paths are resolved to scan_dir / entry.name by the mock_fs.resolve setup)
    expected_path1 = scan_dir / mock_entry_one.name
    expected_path3 = scan_dir / mock_entry_three.name

    found_entry1 = any(
        d.path == expected_path1 and d.mtime == 100.0 and d.size == 10 for d in result
    )
    found_entry3 = any(
        d.path == expected_path3 and d.mtime == 300.0 and d.size == 30 for d in result
    )
    assert found_entry1, "Mock entry one not found or incorrect in results"
    assert found_entry3, "Mock entry three not found or incorrect in results"

    # Check logs for the problematic entry
    # Ensure at least one log message matches the expected error/warning
    found_log_message = False
    for record in caplog.records:
        if record.levelno == expected_log_level:
            if (
                log_msg_substring_key in record.message
                and mock_entry_two_problematic.name in record.message
            ):
                # Check if the original exception type matches if exc_info is expected
                if expect_exc_info:
                    assert record.exc_info is not None, "Expected exc_info to be logged"
                    assert isinstance(record.exc_info[1], type(exception_type)), (
                        f"Logged exception type mismatch. Got {type(record.exc_info[1])}, expected {type(exception_type)}"
                    )
                else:
                    assert record.exc_info is None, "Expected exc_info to be None"
                found_log_message = True
                break
    assert found_log_message, (
        f"Expected log message containing '{log_msg_substring_key}' for entry '{mock_entry_two_problematic.name}' not found. Logs:\n{caplog.text}"
    )

    # Verify calls to fs.resolve for the successful entries
    # For the "resolve" error stage, fs.resolve would also be called for the problematic entry (and then raise an error)
    mock_fs.resolve.assert_any_call(Path(mock_entry_one.path), strict=False)
    mock_fs.resolve.assert_any_call(Path(mock_entry_three.path), strict=False)
    if error_stage == "resolve":
        mock_fs.resolve.assert_any_call(
            Path(mock_entry_two_problematic.path), strict=False
        )


def test_logging_summary_no_files_found(
    scan_dir: Path, mock_fs: MagicMock, caplog: pytest.LogCaptureFixture
):
    """Test the debug log message when no regular files are found but scan is successful."""
    mock_fs.scandir.return_value.__enter__.return_value = iter([])  # Empty directory

    with caplog.at_level(logging.DEBUG):
        result = gather_file_data(scan_dir, mock_fs)

    assert result == []
    assert (
        f"Successfully scanned directory '{scan_dir}', but found no regular files."
        in caplog.text
    )


def test_logging_summary_files_found(
    scan_dir: Path, mock_fs: MagicMock, caplog: pytest.LogCaptureFixture
):
    """Test the debug log message when regular files are found."""
    entry1 = make_mock_dir_entry(
        "file1.txt", scan_dir, stat_result=create_mock_stat_attrs(100.0, 10)
    )
    mock_fs.scandir.return_value.__enter__.return_value = iter([entry1])
    mock_fs.resolve.return_value = scan_dir / "resolved_file1.txt"

    with caplog.at_level(logging.DEBUG):
        result = gather_file_data(scan_dir, mock_fs)

    assert len(result) == 1
    assert f"Gathered data for 1 regular files in {scan_dir}" in caplog.text
    assert f"Gathered data for: {scan_dir / 'resolved_file1.txt'}" in caplog.text
