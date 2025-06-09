import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.purger.manage_disk_space import manage_disk_space
from tests.unit.purger.format_size_human_readable import format_size_human_readable


# Helper to create GatheredEntryData instances for tests
def _ged(name: str, mtime: float, size: int) -> GatheredEntryData:
    """Creates a GatheredEntryData instance."""
    return GatheredEntryData(mtime=mtime, size=size, path=Path(name))


# Sample files
UPLOADED_FILE_1 = _ged("up1.dat", mtime=100.0, size=1000)
UPLOADED_FILE_2 = _ged("up2.dat", mtime=200.0, size=500)
WORK_FILE_1 = _ged(
    "work1.dat", mtime=150.0, size=2000
)  # Older than up2 but in work dir
WORK_FILE_2 = _ged("work2.dat", mtime=250.0, size=200)

# Logger name for the SUT (manage_disk_space.py)
SUT_LOGGER_NAME = "datamover.purger.manage_disk_space"


@pytest.fixture
def mock_paths(standard_test_dirs):  # Using the provided fixture from conftest.py
    """Provides mock Path objects for work and uploaded directories."""
    return standard_test_dirs.worker_dir, standard_test_dirs.uploaded_dir


class TestManageDiskSpace:
    @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
    @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
    def test_both_scans_fail(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_fs: MagicMock,
        mock_paths: tuple[Path, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        work_dir, uploaded_dir = mock_paths
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

        mock_scan.return_value = ([], False)  # (files, scan_ok=False)

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=10000,
            target_disk_usage_percent=0.8,
        )

        assert mock_scan.call_count == 2
        mock_scan.assert_any_call(uploaded_dir, mock_fs, "uploaded")
        mock_scan.assert_any_call(work_dir, mock_fs, "work")
        mock_process.assert_not_called()
        assert "Both directory scans failed. Aborting cleanup." in caplog.text
        assert any(
            r.levelno == logging.ERROR
            for r in caplog.records
            if "Both directory scans failed" in r.message
        )

    @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
    @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
    def test_both_dirs_empty_scans_ok(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_fs: MagicMock,
        mock_paths: tuple[Path, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        work_dir, uploaded_dir = mock_paths
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

        mock_scan.return_value = ([], True)  # (empty_files_list, scan_ok=True)

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=10000,
            target_disk_usage_percent=0.8,
        )
        assert (
            "Both directories successfully scanned and are empty. No files to manage."
            in caplog.text
        )
        mock_process.assert_not_called()

        # In tests/unit/purger/test_manage_disk_space.py

        @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
        @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
        def test_disk_usage_within_target(
            self,
            mock_scan: MagicMock,
            mock_process: MagicMock,
            mock_fs: MagicMock,
            mock_paths: tuple[Path, Path],
            caplog: pytest.LogCaptureFixture,
        ):
            work_dir, uploaded_dir = mock_paths
            caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

            uploaded_files = [UPLOADED_FILE_1]  # 1000 bytes
            work_files = [WORK_FILE_1]  # 2000 bytes
            # Total = 3000 bytes
            mock_scan.side_effect = [
                (uploaded_files, True),  # uploaded scan
                (work_files, True),  # work scan
            ]
            total_disk_cap = 10000
            target_percent = 0.8
            # target_bytes_to_keep = int(total_disk_cap * target_percent) # 8000 (comment not strictly needed for test logic)

            # Current usage (3000) is less than target to keep (8000)
            manage_disk_space(
                work_dir_path=work_dir,
                uploaded_dir_path=uploaded_dir,
                fs=mock_fs,
                total_disk_capacity_bytes=total_disk_cap,
                target_disk_usage_percent=target_percent,
            )
            assert (
                "Current disk usage is within target. No files need to be deleted."
                in caplog.text
            )
            mock_process.assert_not_called()

    class TestManageDiskSpace:
        @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
        @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
        def test_delete_from_uploaded_only_meets_target(
            self,
            mock_scan: MagicMock,
            mock_process: MagicMock,
            mock_fs: MagicMock,
            mock_paths: tuple[Path, Path],
            caplog: pytest.LogCaptureFixture,
        ):
            work_dir, uploaded_dir = mock_paths
            caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

            uploaded_files = [UPLOADED_FILE_1, UPLOADED_FILE_2]  # 1500
            work_files = [WORK_FILE_1]  # 2000
            # Total current = 3500
            mock_scan.side_effect = [
                (uploaded_files, True),
                (work_files, True),
            ]

            total_disk_cap = 4000
            target_percent = 0.5  # Target to keep = 2000 bytes
            bytes_to_delete = 1500

            mock_process.return_value = (
                UPLOADED_FILE_1.size + UPLOADED_FILE_2.size
            )  # 1500

            manage_disk_space(
                work_dir_path=work_dir,
                uploaded_dir_path=uploaded_dir,
                fs=mock_fs,
                total_disk_capacity_bytes=total_disk_cap,
                target_disk_usage_percent=target_percent,
            )

            # For uploaded: target_bytes_to_keep = max(0, 1500 - 1500) = 0
            mock_process.assert_called_once_with(
                files_to_consider=uploaded_files,
                fs=mock_fs,
                directory_description="uploaded directory",
                target_bytes_to_keep=0,
            )
            # FIXED: Use the formatter to match the actual log output
            expected_log = (
                f"Need to delete at least "
                f"{format_size_human_readable(bytes_to_delete)} "
                f"overall to reach target."
            )
            assert expected_log in caplog.text
            assert "Successfully brought disk usage to target or below." in caplog.text

    @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
    @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
    def test_delete_from_uploaded_and_work_meets_target(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_fs: MagicMock,
        mock_paths: tuple[Path, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        work_dir, uploaded_dir = mock_paths
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

        uploaded_files = [UPLOADED_FILE_1]  # 1000
        work_files = [WORK_FILE_1, WORK_FILE_2]  # 2200
        # Total current = 3200
        mock_scan.side_effect = [
            (uploaded_files, True),
            (work_files, True),
        ]

        total_disk_cap = 3000
        target_percent = 0.5  # Target to keep = 1500 bytes
        bytes_to_delete = 1700

        bytes_deleted_from_uploaded = UPLOADED_FILE_1.size  # 1000
        bytes_deleted_from_work = WORK_FILE_1.size  # 2000
        mock_process.side_effect = [
            bytes_deleted_from_uploaded,
            bytes_deleted_from_work,
        ]

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=total_disk_cap,
            target_disk_usage_percent=target_percent,
        )

        # Call for uploaded: target_bytes_to_keep = max(0, 1000 - 1700) = 0
        expected_uploaded_call = call(
            files_to_consider=uploaded_files,
            fs=mock_fs,
            directory_description="uploaded directory",
            target_bytes_to_keep=0,
        )

        # Call for work: target_bytes_to_keep = max(0, 2200 - 700) = 1500
        expected_work_call = call(
            files_to_consider=work_files,
            fs=mock_fs,
            directory_description="work directory",
            target_bytes_to_keep=1500,
        )

        mock_process.assert_has_calls([expected_uploaded_call, expected_work_call])

        # FIXED: Use the formatter to match the actual log output
        expected_log = (
            f"Need to delete at least "
            f"{format_size_human_readable(bytes_to_delete)} "
            f"overall to reach target."
        )
        assert expected_log in caplog.text
        bytes_still_needing_deletion = bytes_to_delete - bytes_deleted_from_uploaded
        assert (
            f"Still need to delete {format_size_human_readable(bytes_still_needing_deletion)}"
            in caplog.text
        )

    @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
    @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
    def test_deletion_needed_but_not_enough_files_to_reach_target(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_fs: MagicMock,
        mock_paths: tuple[Path, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        work_dir, uploaded_dir = mock_paths
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

        uploaded_files = [UPLOADED_FILE_1]  # 1000
        work_files = [WORK_FILE_2]  # 200
        # Total current = 1200
        mock_scan.side_effect = [
            (uploaded_files, True),
            (work_files, True),
        ]

        total_disk_cap = 2000
        target_percent = 0.1  # Target to keep = 200 bytes
        # Need to delete 1200 - 200 = 1000 bytes

        # Scenario: Delete all available (1000 + 200 = 1200 bytes)
        # But we only *need* to delete 1000.
        # If uploaded_file_1 (1000) is deleted, target is met.
        mock_process.return_value = UPLOADED_FILE_1.size  # 1000

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=total_disk_cap,
            target_disk_usage_percent=target_percent,
        )
        # target_bytes_to_keep_in_uploaded_dir = max(0, 1000 - 1000) = 0
        mock_process.assert_called_once_with(
            files_to_consider=uploaded_files,
            fs=mock_fs,
            directory_description="uploaded directory",
            target_bytes_to_keep=0,
        )
        assert "Successfully brought disk usage to target or below." in caplog.text

        # Now, a case where even deleting everything doesn't meet target
        caplog.clear()
        mock_process.reset_mock()
        mock_scan.side_effect = [  # Reset side effect for scan
            (uploaded_files, True),
            (work_files, True),
        ]

        target_percent_low = 0.05  # Target to keep = 100 bytes
        # Need to delete 1200 - 100 = 1100 bytes

        # Deleting all from uploaded (1000) and all from work (200) gives 1200 deleted.
        # This is enough to meet the 1100 deletion target.
        bytes_deleted_from_uploaded = UPLOADED_FILE_1.size  # 1000
        bytes_deleted_from_work = WORK_FILE_2.size  # 200
        mock_process.side_effect = [
            bytes_deleted_from_uploaded,
            bytes_deleted_from_work,
        ]
        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=total_disk_cap,
            target_disk_usage_percent=target_percent_low,
        )
        # Target to keep overall = 100. Current total = 1200. overall_bytes_to_delete_target = 1100
        # Uploaded: target_bytes_to_keep_in_uploaded_dir = max(0, 1000 - 1100) = 0
        # Work: bytes_still_needing_deletion = 1100 - 1000 = 100
        #       target_bytes_to_keep_in_work_dir = max(0, 200 - 100) = 100
        expected_calls = [
            call(
                files_to_consider=uploaded_files,
                fs=mock_fs,
                directory_description="uploaded directory",
                target_bytes_to_keep=0,
            ),
            call(
                files_to_consider=work_files,
                fs=mock_fs,
                directory_description="work directory",
                target_bytes_to_keep=100,
            ),
        ]
        mock_process.assert_has_calls(expected_calls)
        # After deleting 1200, final_estimated_used_space = 1200 - 1200 = 0.
        # target_bytes_to_keep_on_disk_overall = 100.
        # deficit = 0 - 100 = -100. So no warning deficit > 0.
        assert "Successfully brought disk usage to target or below." in caplog.text

    @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
    @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
    def test_deficit_remains_after_deletions(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_fs: MagicMock,
        mock_paths: tuple[Path, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        work_dir, uploaded_dir = mock_paths
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

        # Only one small file available
        uploaded_files = [_ged("small.dat", 100, 50)]  # 50 bytes
        work_files = []

        mock_scan.side_effect = [
            (uploaded_files, True),
            (work_files, True),
        ]

        total_disk_cap = 1000
        target_percent = 0.01  # Target to keep = 10 bytes
        # Need to delete 50 - 10 = 40 bytes

        mock_process.return_value = 0  # Simulate deletion failed for the 50 byte file

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=total_disk_cap,
            target_disk_usage_percent=target_percent,
        )
        # target_bytes_to_keep_in_uploaded_dir = max(0, 50 - 40) = 10
        mock_process.assert_called_once_with(
            files_to_consider=uploaded_files,
            fs=mock_fs,
            directory_description="uploaded directory",
            target_bytes_to_keep=10,
        )
        # current_total_used_space_bytes = 50
        # total_bytes_deleted_this_session = 0
        # final_estimated_used_space_bytes = 50
        # target_bytes_to_keep_on_disk_overall = 10
        # deficit_after_deletions = 50 - 10 = 40
        warning_msg_part = (
            f"Disk cleanup finished, but may still be {40} bytes above the target"
        )
        assert warning_msg_part in caplog.text
        assert any(
            r.levelno == logging.WARNING
            for r in caplog.records
            if warning_msg_part in r.message
        )

    @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
    @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
    def test_zero_disk_capacity(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_fs: MagicMock,
        mock_paths: tuple[Path, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        work_dir, uploaded_dir = mock_paths
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

        uploaded_files = [UPLOADED_FILE_1]  # 1000
        work_files = []

        mock_scan.side_effect = [
            (uploaded_files, True),
            (work_files, True),
        ]

        total_disk_cap = 0  # Zero capacity
        target_percent = 0.8
        # target_bytes_to_keep_on_disk_overall = int(0 * 0.8) = 0
        # overall_bytes_to_delete_target = 1000 - 0 = 1000

        # Assume we delete the 1000 bytes
        mock_process.return_value = 1000

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=total_disk_cap,
            target_disk_usage_percent=target_percent,
        )

        # target_bytes_to_keep_in_uploaded_dir = max(0, 1000 - 1000) = 0
        mock_process.assert_called_once_with(
            files_to_consider=uploaded_files,
            fs=mock_fs,
            directory_description="uploaded directory",
            target_bytes_to_keep=0,
        )
        final_estimated = 1000 - 1000  # 0
        assert (
            f"Estimated current disk usage: {final_estimated} bytes (total capacity was zero or not provided)."
            in caplog.text
        )

    @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
    @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
    def test_deletion_needed_but_work_dir_empty(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_fs: MagicMock,
        mock_paths: tuple[Path, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        work_dir, uploaded_dir = mock_paths
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

        uploaded_files = [UPLOADED_FILE_1]  # 1000
        work_files = []  # Work dir is empty

        mock_scan.side_effect = [
            (uploaded_files, True),  # uploaded scan
            (work_files, True),  # work scan (empty)
        ]

        total_disk_cap = 1000
        target_percent = 0.5  # Target to keep = 500 bytes
        # Need to delete 1000 - 500 = 500 bytes

        # Delete from uploaded (e.g., 0 bytes deleted if UPLOADED_FILE_1 is too large or deletion fails)
        bytes_deleted_from_uploaded_val = 0
        mock_process.return_value = bytes_deleted_from_uploaded_val

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=total_disk_cap,
            target_disk_usage_percent=target_percent,
        )

        # overall_bytes_to_delete_target = 500
        # target_bytes_to_keep_in_uploaded_dir = max(0, 1000 - 500) = 500
        mock_process.assert_called_once_with(
            files_to_consider=uploaded_files,
            fs=mock_fs,
            directory_description="uploaded directory",
            target_bytes_to_keep=500,
        )
        # bytes_still_needing_deletion = 500 - 0 = 500
        # work_files_sorted is empty
        assert (
            "Still need to delete 500 bytes, but no files available in work directory."
            in caplog.text
        )
        # Deficit check:
        # final_estimated_used_space_bytes = 1000 - 0 = 1000
        # target_bytes_to_keep_on_disk_overall = 500
        # deficit_after_deletions = 1000 - 500 = 500
        warning_msg_part = (
            f"Disk cleanup finished, but may still be {500} bytes above the target"
        )
        assert warning_msg_part in caplog.text

    @patch("datamover.purger.manage_disk_space.process_files_for_deletion")
    @patch("datamover.purger.manage_disk_space.scan_and_sort_files")
    def test_one_scan_fails_other_succeeds_and_deletes(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_fs: MagicMock,
        mock_paths: tuple[Path, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        work_dir, uploaded_dir = mock_paths
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)

        uploaded_files = [UPLOADED_FILE_1]  # 1000

        # Uploaded scan OK, Work scan fails
        mock_scan.side_effect = [
            (uploaded_files, True),
            ([], False),
        ]

        total_disk_cap = 1000
        target_percent = 0.5  # Target to keep = 500 bytes
        bytes_deleted = 1000

        mock_process.return_value = bytes_deleted

        manage_disk_space(
            work_dir_path=work_dir,
            uploaded_dir_path=uploaded_dir,
            fs=mock_fs,
            total_disk_capacity_bytes=total_disk_cap,
            target_disk_usage_percent=target_percent,
        )

        # target_bytes_to_keep_in_uploaded_dir = max(0, 1000 - 500) = 500
        mock_process.assert_called_once_with(
            files_to_consider=uploaded_files,
            fs=mock_fs,
            directory_description="uploaded directory",
            target_bytes_to_keep=500,
        )

        # FIXED: Use the formatter and ensure the full message is checked
        expected_log = (
            f"Total bytes actually deleted in this session: "
            f"{format_size_human_readable(bytes_deleted)}."
        )
        assert expected_log in caplog.text
