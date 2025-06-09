import logging
import time
from pathlib import Path
from typing import NamedTuple, Dict, Any

import pytest

# --- Application Imports ---
from datamover.file_functions.fs_mock import FS  # Your concrete FS implementation
from datamover.purger.manage_disk_space import manage_disk_space
from tests.test_utils.fs_helpers import create_and_stamp_real_fs

logger = logging.getLogger(__name__)
SUT_LOGGER_NAME = "datamover.purger.manage_disk_space"
SCAN_LOGGER_NAME = "datamover.purger.scan_and_sort_files"
PROCESS_LOGGER_NAME = "datamover.purger.process_files_for_deletion"


class PurgerTestDirs(NamedTuple):
    work_dir: Path
    uploaded_dir: Path


@pytest.fixture
def purger_test_dirs(tmp_path: Path) -> PurgerTestDirs:
    """Creates temporary directories for purger integration tests."""
    base = tmp_path / "purger_integration_root"
    work = base / "work_files"
    uploaded = base / "uploaded_files"

    work.mkdir(parents=True, exist_ok=True)
    uploaded.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created purger integration dirs: work={work}, uploaded={uploaded}")
    return PurgerTestDirs(work_dir=work, uploaded_dir=uploaded)


def create_files_for_purging(
    fs: FS, base_dir: Path, file_specs: Dict[str, Dict[str, Any]]
):
    """Helper to create files with specific size and mtime."""
    for name, spec in file_specs.items():
        path = base_dir / name
        create_and_stamp_real_fs(
            fs_operations=fs,
            full_path=path,
            size=spec["size"],
            mtime=spec["mtime"],
        )
        logger.debug(
            f"Created file for purger test: {path} (size: {spec['size']}, mtime: {spec['mtime']})"
        )


@pytest.mark.integration  # Mark as an integration test
class TestPurgerIntegration:
    def test_deletes_oldest_from_uploaded_then_work_to_meet_target(
        self,
        purger_test_dirs: PurgerTestDirs,
        real_fs: FS,  # From conftest.py, this is your ConcreteFSImpl
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)  # Capture detailed logs for debugging
        work_dir = purger_test_dirs.work_dir
        uploaded_dir = purger_test_dirs.uploaded_dir

        time_now = time.time()
        # Files sorted by age: up_oldest, work_older, up_new, work_newest
        files_in_uploaded = {
            "up_oldest.dat": {"size": 1000, "mtime": time_now - 300},  # Oldest overall
            "up_new.dat": {"size": 500, "mtime": time_now - 100},  # Newer
        }
        files_in_work = {
            "work_older.dat": {"size": 2000, "mtime": time_now - 200},  # Mid age
            "work_newest.dat": {"size": 200, "mtime": time_now - 50},  # Newest overall
        }

        create_files_for_purging(real_fs, uploaded_dir, files_in_uploaded)
        create_files_for_purging(real_fs, work_dir, files_in_work)

        _total_initial_size = 1000 + 500 + 2000 + 200  # 3700 bytes
        total_disk_capacity = 5000
        target_disk_usage_percent = 0.30  # Target to keep = 5000 * 0.30 = 1500 bytes
        # Need to delete = 3700 - 1500 = 2200 bytes

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=real_fs,  # Use the real FS implementation
            total_disk_capacity_bytes=total_disk_capacity,
            target_disk_usage_percent=target_disk_usage_percent,
        )

        # According to SUT logic and the rule:
        # overall_bytes_to_delete_target = 2200
        # For uploaded_dir: target_bytes_to_keep_in_uploaded_dir = max(0, 1500 - 2200) = 0.
        # This means the SUT will try to empty the uploaded_dir.
        assert not real_fs.exists(uploaded_dir / "up_oldest.dat"), (
            "up_oldest.dat should be deleted from uploaded"
        )
        assert not real_fs.exists(uploaded_dir / "up_new.dat"), (
            "up_new.dat should also be deleted from uploaded"
        )  # Key change

        # After processing uploaded_dir, 1500 bytes were deleted.
        # Bytes still needing deletion for overall target: 2200 - 1500 = 700.
        # For work_dir (total 2200 bytes: work_older.dat 2000, work_newest.dat 200):
        # target_bytes_to_keep_in_work_dir = max(0, 2200 - 700) = 1500.
        # To get work_dir down to 1500 (from 2200), work_older.dat (2000 bytes) will be deleted.
        # This leaves work_newest.dat (200 bytes), which is < 1500.
        assert not real_fs.exists(work_dir / "work_older.dat"), (
            "work_older.dat should be deleted from work"
        )
        assert real_fs.exists(work_dir / "work_newest.dat"), (
            "work_newest.dat should remain in work"
        )

        # Verify logs (optional, but good for confirming behavior)
        assert f"Need to delete at least {2200} bytes overall" in caplog.text
        assert any(
            PROCESS_LOGGER_NAME == rec.name
            and f"Successfully deleted: {uploaded_dir / 'up_oldest.dat'}" in rec.message
            for rec in caplog.records
        )
        assert any(  # Check for up_new.dat deletion log
            PROCESS_LOGGER_NAME == rec.name
            and f"Successfully deleted: {uploaded_dir / 'up_new.dat'}" in rec.message
            for rec in caplog.records
        )
        assert any(
            PROCESS_LOGGER_NAME == rec.name
            and f"Successfully deleted: {work_dir / 'work_older.dat'}" in rec.message
            for rec in caplog.records
        )
        assert "Successfully brought disk usage to target or below." in caplog.text

        # Verify final disk usage
        remaining_size = 0
        # up_new.dat is now also deleted from uploaded_dir
        if real_fs.exists(
            work_dir / "work_newest.dat"
        ):  # Only work_newest.dat should be left
            remaining_size += real_fs.stat(work_dir / "work_newest.dat").st_size

        expected_remaining_size = files_in_work["work_newest.dat"]["size"]  # 200 bytes
        assert remaining_size == expected_remaining_size, (
            f"Expected remaining size {expected_remaining_size}, got {remaining_size}"
        )

        final_estimated_log = f"Estimated current disk usage: {expected_remaining_size} bytes"  # 200 bytes
        assert any(
            SUT_LOGGER_NAME == rec.name and final_estimated_log in rec.message
            for rec in caplog.records
        )

    def test_no_deletion_if_target_already_met_integration(
        self,
        purger_test_dirs: PurgerTestDirs,
        real_fs: FS,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        work_dir = purger_test_dirs.work_dir
        uploaded_dir = purger_test_dirs.uploaded_dir

        time_now = time.time()
        files_in_uploaded = {"up1.dat": {"size": 100, "mtime": time_now - 10}}
        files_in_work = {"work1.dat": {"size": 200, "mtime": time_now - 20}}
        create_files_for_purging(real_fs, uploaded_dir, files_in_uploaded)
        create_files_for_purging(real_fs, work_dir, files_in_work)

        _total_initial_size = 100 + 200  # 300
        total_disk_capacity = 1000
        target_disk_usage_percent = 0.80  # Target to keep = 800 bytes
        # Current (300) < Target to keep (800)

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=real_fs,
            total_disk_capacity_bytes=total_disk_capacity,
            target_disk_usage_percent=target_disk_usage_percent,
        )

        assert real_fs.exists(uploaded_dir / "up1.dat"), "up1.dat should remain"
        assert real_fs.exists(work_dir / "work1.dat"), "work1.dat should remain"
        assert (
            "Current disk usage is within target. No files need to be deleted."
            in caplog.text
        )

    def test_only_uploaded_files_exist_some_deleted(
        self,
        purger_test_dirs: PurgerTestDirs,
        real_fs: FS,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)
        work_dir = purger_test_dirs.work_dir  # Will remain empty
        uploaded_dir = purger_test_dirs.uploaded_dir

        time_now = time.time()
        files_in_uploaded = {
            "up_oldest.dat": {"size": 1000, "mtime": time_now - 300},
            "up_mid.dat": {"size": 800, "mtime": time_now - 200},
            "up_newest.dat": {"size": 500, "mtime": time_now - 100},
        }
        # No files created in work_dir

        create_files_for_purging(real_fs, uploaded_dir, files_in_uploaded)

        _total_initial_size = 1000 + 800 + 500  # 2300 bytes
        total_disk_capacity = 3000
        # Target to keep = 3000 * 0.30 = 900 bytes
        # Need to delete = 2300 - 900 = 1400 bytes
        target_disk_usage_percent = 0.30

        manage_disk_space(
            work_dir_path=work_dir,  # Pass the empty work_dir path
            uploaded_dir_path=uploaded_dir,
            fs=real_fs,
            total_disk_capacity_bytes=total_disk_capacity,
            target_disk_usage_percent=target_disk_usage_percent,
        )

        # Expected deletions from uploaded_dir:
        # Need to delete 1400 bytes.
        # 1. up_oldest.dat (1000 bytes). Bytes deleted: 1000. Remaining needed: 400.
        # 2. up_mid.dat (800 bytes). Bytes deleted: 1000 + 800 = 1800. Target met (1800 >= 1400).

        assert not real_fs.exists(uploaded_dir / "up_oldest.dat"), (
            "up_oldest.dat should be deleted"
        )
        assert not real_fs.exists(uploaded_dir / "up_mid.dat"), (
            "up_mid.dat should be deleted"
        )
        assert real_fs.exists(uploaded_dir / "up_newest.dat"), (
            "up_newest.dat should remain"
        )

        # Ensure no files appeared in work_dir
        assert not real_fs.listdir(work_dir), (
            "Work directory should remain empty"
        )  # CORRECTED LINE

        # Verify logs
        assert f"Need to delete at least {1400} bytes overall" in caplog.text
        assert any(
            PROCESS_LOGGER_NAME == rec.name
            and f"Successfully deleted: {uploaded_dir / 'up_oldest.dat'}" in rec.message
            for rec in caplog.records
        )
        assert any(
            PROCESS_LOGGER_NAME == rec.name
            and f"Successfully deleted: {uploaded_dir / 'up_mid.dat'}" in rec.message
            for rec in caplog.records
        )
        assert "Processing work directory." not in caplog.text

        assert "Successfully brought disk usage to target or below." in caplog.text

        remaining_size = 0
        if real_fs.exists(uploaded_dir / "up_newest.dat"):
            remaining_size += real_fs.stat(uploaded_dir / "up_newest.dat").st_size

        expected_remaining_size = files_in_uploaded["up_newest.dat"]["size"]  # 500
        assert remaining_size == expected_remaining_size

        final_estimated_log = (
            f"Estimated current disk usage: {expected_remaining_size} bytes"
        )
        assert any(
            SUT_LOGGER_NAME == rec.name and final_estimated_log in rec.message
            for rec in caplog.records
        )

    def test_only_work_files_exist_some_deleted(
        self,
        purger_test_dirs: PurgerTestDirs,
        real_fs: FS,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)
        work_dir = purger_test_dirs.work_dir
        uploaded_dir = purger_test_dirs.uploaded_dir  # Will remain empty

        time_now = time.time()
        # No files created in uploaded_dir
        files_in_work = {
            "work_oldest.dat": {"size": 1200, "mtime": time_now - 400},
            "work_mid.dat": {"size": 700, "mtime": time_now - 250},
            "work_newest.dat": {"size": 300, "mtime": time_now - 50},
        }

        create_files_for_purging(real_fs, work_dir, files_in_work)

        _total_initial_size = 1200 + 700 + 300  # 2200 bytes
        total_disk_capacity = 3000
        # Target to keep = 3000 * 0.20 = 600 bytes
        # Need to delete = 2200 - 600 = 1600 bytes
        target_disk_usage_percent = 0.20

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,  # Pass the empty uploaded_dir path
            fs=real_fs,
            total_disk_capacity_bytes=total_disk_capacity,
            target_disk_usage_percent=target_disk_usage_percent,
        )

        # Expected deletions from work_dir:
        # Uploaded dir is empty, so 0 bytes deleted from there.
        # overall_bytes_to_delete_target = 1600.
        # bytes_still_needing_deletion = 1600 - 0 = 1600.
        # Process work_dir:
        # 1. work_oldest.dat (1200 bytes). Bytes deleted from work: 1200. Remaining needed: 400.
        # 2. work_mid.dat (700 bytes). Bytes deleted from work: 1200 + 700 = 1900. Target met (1900 >= 1600).

        assert not real_fs.exists(work_dir / "work_oldest.dat"), (
            "work_oldest.dat should be deleted"
        )
        assert not real_fs.exists(work_dir / "work_mid.dat"), (
            "work_mid.dat should be deleted"
        )
        assert real_fs.exists(work_dir / "work_newest.dat"), (
            "work_newest.dat should remain"
        )

        # Ensure uploaded_dir remains empty
        assert not real_fs.listdir(uploaded_dir), (
            "Uploaded directory should remain empty"
        )

        # Verify logs
        assert f"Need to delete at least {1600} bytes overall" in caplog.text
        # Check that uploaded directory processing acknowledges it's empty or no deletions from it
        assert any(
            SUT_LOGGER_NAME == rec.name
            and "size_of_uploaded_files = 0"
            or "Uploaded: 0" in rec.message
            for rec in caplog.records
        )  # Or check log for process_files_for_deletion with empty uploaded_files_sorted

        # Check that work directory processing happened
        assert (
            f"Still need to delete {1600} bytes. Processing work directory."
            in caplog.text
        )
        assert any(
            PROCESS_LOGGER_NAME == rec.name
            and f"Successfully deleted: {work_dir / 'work_oldest.dat'}" in rec.message
            for rec in caplog.records
        )
        assert any(
            PROCESS_LOGGER_NAME == rec.name
            and f"Successfully deleted: {work_dir / 'work_mid.dat'}" in rec.message
            for rec in caplog.records
        )

        assert "Successfully brought disk usage to target or below." in caplog.text

        remaining_size = 0
        if real_fs.exists(work_dir / "work_newest.dat"):
            remaining_size += real_fs.stat(work_dir / "work_newest.dat").st_size

        expected_remaining_size = files_in_work["work_newest.dat"]["size"]  # 300
        assert remaining_size == expected_remaining_size

        final_estimated_log = (
            f"Estimated current disk usage: {expected_remaining_size} bytes"
        )
        assert any(
            SUT_LOGGER_NAME == rec.name and final_estimated_log in rec.message
            for rec in caplog.records
        )
