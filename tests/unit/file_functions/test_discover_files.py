import logging
import stat
from pathlib import Path
from typing import Set
from unittest.mock import MagicMock, call

import pytest

from datamover.file_functions.discover_files import discover_files
from tests.test_utils.fs_helpers import create_mock_stat_attrs


def assert_discovery_logs(caplog: pytest.LogCaptureFixture) -> None:
    """
    Asserts that the discovery start and completion messages
    are present in the captured logs, regardless of level.
    """
    log_text = caplog.text
    assert "Discovering initial files" in log_text
    assert "Discovery complete. Found" in log_text


class TestDiscoverFiles:
    @pytest.fixture(autouse=True)
    def caplog_capture(self, caplog: pytest.LogCaptureFixture):
        caplog.set_level(logging.DEBUG)
        return caplog

    @pytest.fixture
    def discovery_base_dir(self, tmp_path: Path) -> Path:
        """
        Provides an empty temporary directory for discovery tests.
        """
        base = tmp_path / "discover_root"
        base.mkdir()
        return base

    def test_empty_directory(
        self,
        mock_fs: MagicMock,
        discovery_base_dir: Path,
        caplog_capture: pytest.LogCaptureFixture,
    ):
        """
        Tests discovery in an empty directory.
        - fs.listdir should be called.
        - fs.lstat should not be called.
        - Result should be an empty set.
        - Logs should include start and complete messages.
        """
        mock_fs.listdir.return_value = []
        # Prevent any lstat calls
        mock_fs.lstat.side_effect = AssertionError(
            "lstat should not be called in empty dir test"
        )

        result = discover_files(discovery_base_dir, mock_fs)

        assert result == set()
        mock_fs.listdir.assert_called_once_with(discovery_base_dir)
        mock_fs.lstat.assert_not_called()

        assert_discovery_logs(caplog_capture)

    def test_directory_with_regular_files(
        self,
        mock_fs: MagicMock,
        discovery_base_dir: Path,
        caplog_capture: pytest.LogCaptureFixture,
    ):
        """
        Tests discovery of multiple regular files.
        - fs.listdir returns filenames.
        - fs.lstat returns S_IFREG for all.
        - Result is set of Paths.
        - Logs should include start and complete messages.
        """
        files = ["file1.dat", "file2.log", "another.txt"]
        mock_fs.listdir.return_value = files
        mock_fs.lstat.side_effect = lambda p: create_mock_stat_attrs(
            st_mode=stat.S_IFREG,
            st_ino=hash(p),
            st_size=100 + len(str(p)),
        )
        expected: Set[Path] = {discovery_base_dir / name for name in files}

        result = discover_files(discovery_base_dir, mock_fs)

        assert result == expected
        mock_fs.listdir.assert_called_once_with(discovery_base_dir)
        calls = [call(discovery_base_dir / name) for name in files]
        mock_fs.lstat.assert_has_calls(calls, any_order=True)
        assert mock_fs.lstat.call_count == len(files)

        assert_discovery_logs(caplog_capture)

    def test_skips_non_regular_files(
        self,
        mock_fs: MagicMock,
        discovery_base_dir: Path,
        caplog_capture: pytest.LogCaptureFixture,
    ):
        """
        Tests skipping non-regular files (dirs, links, pipes).
        - fs.listdir returns mixed entries.
        - fs.lstat returns varying modes.
        - Result only contains regular file.
        - Logs should include start and complete messages.
        """
        entries = ["reg.file", "subdir", "link.lnk", "fifo.pipe"]
        mock_fs.listdir.return_value = entries

        def lstat_side_effect(path: Path):
            name = path.name
            if name == "reg.file":
                return create_mock_stat_attrs(st_mode=stat.S_IFREG, st_ino=1)
            if name in {"subdir", "link.lnk", "fifo.pipe"}:
                mode_map = {
                    "subdir": stat.S_IFDIR,
                    "link.lnk": stat.S_IFLNK,
                    "fifo.pipe": stat.S_IFIFO,
                }
                return create_mock_stat_attrs(st_mode=mode_map[name], st_ino=hash(name))
            assert False, f"Unexpected lstat path: {path}"

        mock_fs.lstat.side_effect = lstat_side_effect
        expected = {discovery_base_dir / "reg.file"}

        result = discover_files(discovery_base_dir, mock_fs)

        assert result == expected
        mock_fs.listdir.assert_called_once_with(discovery_base_dir)
        assert mock_fs.lstat.call_count == len(entries)

        assert_discovery_logs(caplog_capture)

    def test_handles_lstat_oserror_and_continues(
        self,
        mock_fs: MagicMock,
        discovery_base_dir: Path,
        caplog_capture: pytest.LogCaptureFixture,
    ):
        """
        Tests that OSError in lstat for one file is logged and skipped.
        """
        files = ["error.file", "good.file", "another.good"]
        mock_fs.listdir.return_value = files
        err = PermissionError("Mocked: Stat failed for error.file")

        def lstat_side_effect(path: Path):
            name = path.name
            if name == "error.file":
                raise err
            return create_mock_stat_attrs(st_mode=stat.S_IFREG, st_ino=hash(name))

        mock_fs.lstat.side_effect = lstat_side_effect
        expected = {
            discovery_base_dir / "good.file",
            discovery_base_dir / "another.good",
        }

        result = discover_files(discovery_base_dir, mock_fs)

        assert result == expected
        mock_fs.listdir.assert_called_once_with(discovery_base_dir)
        assert mock_fs.lstat.call_count == len(files)

        assert_discovery_logs(caplog_capture)

    def test_handles_lstat_generic_exception_and_continues(
        self,
        mock_fs: MagicMock,
        discovery_base_dir: Path,
        caplog_capture: pytest.LogCaptureFixture,
    ):
        """
        Tests that a generic Exception during fs.lstat (called by safe_stat)
        for one file is logged (by safe_stat or discover_files) and the file is skipped.
        This aims to cover the inner `except Exception:` in discover_files.
        """
        files = ["generic_error.file", "ok.file"]
        mock_fs.listdir.return_value = files
        error_file_path = discovery_base_dir / "generic_error.file"
        generic_err = ValueError("A non-OSError during lstat")

        def lstat_side_effect(path: Path):
            if path == error_file_path:
                raise generic_err  # This error will be raised inside safe_stat
            return create_mock_stat_attrs(st_mode=stat.S_IFREG, st_ino=hash(path))

        mock_fs.lstat.side_effect = lstat_side_effect
        expected = {discovery_base_dir / "ok.file"}

        result = discover_files(discovery_base_dir, mock_fs)

        assert result == expected
        mock_fs.listdir.assert_called_once_with(discovery_base_dir)
        assert mock_fs.lstat.call_count == len(files)

        assert_discovery_logs(caplog_capture)

        found_log_from_safe_stat = False

        for record in caplog_capture.records:
            # Log from safe_stat.py
            if (
                record.levelno == logging.ERROR
                and "safe_stat" in record.pathname
                and error_file_path.name in record.message
            ):
                assert record.exc_info is not None
                _, exc_val, _ = record.exc_info
                assert isinstance(exc_val, ValueError)
                found_log_from_safe_stat = True
            # Log from discover_files.py's inner generic exception handler
            if (
                record.levelno == logging.ERROR
                and "discover_files.py" in record.pathname
                and f"Unexpected error processing item {error_file_path}"
                in record.message
            ):
                assert record.exc_info is not None
                _, exc_val, _ = record.exc_info
                assert isinstance(exc_val, ValueError)  # If safe_stat re-raised it.

        assert found_log_from_safe_stat, (
            "Expected logger.exception log from safe_stat not found for generic_error.file"
        )

        assert (
            f"Discovered initial file: {discovery_base_dir / 'ok.file'}"
            in caplog_capture.text
        )

    def test_listdir_raises_generic_exception(
        self,
        mock_fs: MagicMock,
        discovery_base_dir: Path,
        caplog_capture: pytest.LogCaptureFixture,
    ):
        """
        Tests behavior when fs.listdir itself raises a non-OSError Exception.
        This covers the outer `except Exception`.
        """
        generic_err = RuntimeError("Unexpected listdir failure (mocked)")
        mock_fs.listdir.side_effect = generic_err

        result = discover_files(discovery_base_dir, mock_fs)

        assert result == set()  # Should return an empty set
        mock_fs.listdir.assert_called_once_with(discovery_base_dir)
        mock_fs.lstat.assert_not_called()

        # Check for logger.exception behavior
        found_log = False
        for record in caplog_capture.records:
            if (
                record.levelno == logging.ERROR
                and f"Unexpected error discovering files in {discovery_base_dir}"
                in record.message
            ):
                assert record.exc_info is not None  # logger.exception sets exc_info
                _, exc_val, _ = record.exc_info
                assert isinstance(exc_val, RuntimeError)
                found_log = True
                break
        assert found_log, "Expected logger.exception log not found for listdir failure"
        assert "Discovery complete. Found" not in caplog_capture.text
