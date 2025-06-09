import logging
from datetime import datetime  # <-- Import datetime
from pathlib import Path
from typing import List
from unittest.mock import patch, MagicMock, call

import pytest

from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.file_functions.safe_delete import DeleteValidationError

# Import the function and the new helper for consistent formatting
from datamover.purger.process_files_for_deletion import (
    process_files_for_deletion,
    format_size_human_readable,
)


# Helper to create GatheredEntryData instances for tests
def _ged(name: str, mtime: float, size: int) -> GatheredEntryData:
    """Creates a GatheredEntryData instance."""
    return GatheredEntryData(mtime=mtime, size=size, path=Path(name))


# Sample files for testing
FILE_1 = _ged("file1.dat", mtime=100.0, size=1000)
FILE_2 = _ged("file2.dat", mtime=200.0, size=500)
FILE_3 = _ged("file3.dat", mtime=300.0, size=2000)

SAMPLE_FILES_TO_CONSIDER: List[GatheredEntryData] = [FILE_1, FILE_2, FILE_3]
TOTAL_SIZE_SAMPLE_FILES = sum(f.size for f in SAMPLE_FILES_TO_CONSIDER)  # 3500
DIR_DESC = "test_directory"
SUT_LOGGER_NAME = "datamover.purger.process_files_for_deletion"


class TestProcessFilesForDeletion:
    def test_no_files_to_consider(
        self, mock_fs: MagicMock, caplog: pytest.LogCaptureFixture
    ):
        """Test when the input list of files is empty."""
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)
        bytes_deleted = process_files_for_deletion(
            files_to_consider=[],
            fs=mock_fs,
            directory_description=DIR_DESC,
            target_bytes_to_keep=100,
        )
        assert bytes_deleted == 0
        assert f"No files in {DIR_DESC} to process for deletion." in caplog.text

    @patch("datamover.purger.process_files_for_deletion.select_files_to_delete")
    def test_no_files_selected_for_deletion(
        self,
        mock_select_files: MagicMock,
        mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test when files are considered, but none are selected for deletion."""
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)
        mock_select_files.return_value = []  # select_files_to_delete returns empty list

        bytes_deleted = process_files_for_deletion(
            files_to_consider=SAMPLE_FILES_TO_CONSIDER,
            fs=mock_fs,
            directory_description=DIR_DESC,
            target_bytes_to_keep=TOTAL_SIZE_SAMPLE_FILES,  # Target to keep all
        )

        mock_select_files.assert_called_once_with(
            all_files=SAMPLE_FILES_TO_CONSIDER,
            current_total_size=TOTAL_SIZE_SAMPLE_FILES,
            target_bytes_to_keep=TOTAL_SIZE_SAMPLE_FILES,
        )
        assert bytes_deleted == 0
        assert (
            f"Selected 0 files from {DIR_DESC} for potential deletion." in caplog.text
        )
        assert f"Actually deleted" not in caplog.text

    @patch("datamover.purger.process_files_for_deletion.safe_delete")
    @patch("datamover.purger.process_files_for_deletion.select_files_to_delete")
    def test_all_selected_files_deleted_successfully(
        self,
        mock_select_files: MagicMock,
        mock_safe_delete: MagicMock,
        mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test when selected files are successfully deleted."""
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)
        files_to_be_deleted = [FILE_1, FILE_2]
        mock_select_files.return_value = files_to_be_deleted
        mock_safe_delete.return_value = None

        target_keep = TOTAL_SIZE_SAMPLE_FILES - (FILE_1.size + FILE_2.size)

        bytes_deleted = process_files_for_deletion(
            files_to_consider=SAMPLE_FILES_TO_CONSIDER,
            fs=mock_fs,
            directory_description=DIR_DESC,
            target_bytes_to_keep=target_keep,
        )

        mock_select_files.assert_called_once_with(
            all_files=SAMPLE_FILES_TO_CONSIDER,
            current_total_size=TOTAL_SIZE_SAMPLE_FILES,
            target_bytes_to_keep=target_keep,
        )

        expected_safe_delete_calls = [
            call(FILE_1.path, mock_fs),
            call(FILE_2.path, mock_fs),
        ]
        mock_safe_delete.assert_has_calls(expected_safe_delete_calls, any_order=False)
        assert mock_safe_delete.call_count == len(files_to_be_deleted)

        expected_bytes_deleted = FILE_1.size + FILE_2.size
        assert bytes_deleted == expected_bytes_deleted

        assert (
            f"Selected {len(files_to_be_deleted)} files from {DIR_DESC} for potential deletion."
            in caplog.text
        )

        # --- MODIFIED ASSERTIONS ---
        for file_entry in files_to_be_deleted:
            readable_size = format_size_human_readable(file_entry.size)
            readable_mtime = datetime.fromtimestamp(file_entry.mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            expected_log = (
                f"Successfully deleted: {file_entry.path} "
                f"(size: {readable_size}, time: {readable_mtime}) "
                f"from {DIR_DESC}."
            )
            assert expected_log in caplog.text

        # Check the final deletion summary uses human-readable format
        readable_total = format_size_human_readable(expected_bytes_deleted)
        assert f"Actually deleted {readable_total} from {DIR_DESC}." in caplog.text

    @patch("datamover.purger.process_files_for_deletion.safe_delete")
    @patch("datamover.purger.process_files_for_deletion.select_files_to_delete")
    def test_some_deletions_fail_with_deletevalidationerror(
        self,
        mock_select_files: MagicMock,
        mock_safe_delete: MagicMock,
        mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test when some deletions fail with DeleteValidationError."""
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)
        files_to_be_deleted = [FILE_1, FILE_2, FILE_3]
        mock_select_files.return_value = files_to_be_deleted

        error_message = "Test DeleteValidationError"
        mock_safe_delete.side_effect = [
            None,  # FILE_1 succeeds
            DeleteValidationError(error_message),  # FILE_2 fails
            None,  # FILE_3 succeeds
        ]

        bytes_deleted = process_files_for_deletion(
            files_to_consider=SAMPLE_FILES_TO_CONSIDER,
            fs=mock_fs,
            directory_description=DIR_DESC,
            target_bytes_to_keep=0,
        )

        mock_safe_delete.assert_has_calls(
            [call(f.path, mock_fs) for f in files_to_be_deleted], any_order=False
        )

        expected_bytes_deleted = FILE_1.size + FILE_3.size
        assert bytes_deleted == expected_bytes_deleted

        # --- MODIFIED ASSERTIONS ---
        for file_entry in [FILE_1, FILE_3]:  # Check logs for successful deletions
            readable_size = format_size_human_readable(file_entry.size)
            readable_mtime = datetime.fromtimestamp(file_entry.mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            expected_log = (
                f"Successfully deleted: {file_entry.path} "
                f"(size: {readable_size}, time: {readable_mtime}) "
                f"from {DIR_DESC}."
            )
            assert expected_log in caplog.text

        warning_msg = f"Could not delete file {FILE_2.path} from {DIR_DESC}: {error_message}. Skipping."
        assert warning_msg in caplog.text
        assert any(r.levelno == logging.WARNING for r in caplog.records)

        # Check the final deletion summary uses human-readable format
        readable_total = format_size_human_readable(expected_bytes_deleted)
        assert f"Actually deleted {readable_total} from {DIR_DESC}." in caplog.text

    @patch("datamover.purger.process_files_for_deletion.safe_delete")
    @patch("datamover.purger.process_files_for_deletion.select_files_to_delete")
    def test_some_deletions_fail_with_other_exception(
        self,
        mock_select_files: MagicMock,
        mock_safe_delete: MagicMock,
        mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test when some deletions fail with a generic Exception."""
        caplog.set_level(logging.INFO, logger=SUT_LOGGER_NAME)
        files_to_be_deleted = [FILE_1, FILE_2]
        mock_select_files.return_value = files_to_be_deleted

        generic_error_message = "Test Generic Exception"
        mock_safe_delete.side_effect = [
            None,  # FILE_1 succeeds
            RuntimeError(generic_error_message),  # FILE_2 fails
        ]

        bytes_deleted = process_files_for_deletion(
            files_to_consider=SAMPLE_FILES_TO_CONSIDER,
            fs=mock_fs,
            directory_description=DIR_DESC,
            target_bytes_to_keep=0,
        )

        expected_bytes_deleted = FILE_1.size
        assert bytes_deleted == expected_bytes_deleted

        # --- MODIFIED ASSERTION ---
        readable_size = format_size_human_readable(FILE_1.size)
        readable_mtime = datetime.fromtimestamp(FILE_1.mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        expected_log = (
            f"Successfully deleted: {FILE_1.path} "
            f"(size: {readable_size}, time: {readable_mtime}) "
            f"from {DIR_DESC}."
        )
        assert expected_log in caplog.text

        error_msg = f"Unexpected error deleting file {FILE_2.path} from {DIR_DESC}: {generic_error_message}. Skipping."
        assert error_msg in caplog.text
        assert any(
            r.levelno == logging.ERROR and r.exc_info is not None
            for r in caplog.records
        )

        # Check the final deletion summary uses human-readable format
        readable_total = format_size_human_readable(expected_bytes_deleted)
        assert f"Actually deleted {readable_total} from {DIR_DESC}." in caplog.text

    @patch("datamover.purger.process_files_for_deletion.safe_delete")
    @patch("datamover.purger.process_files_for_deletion.select_files_to_delete")
    def test_no_bytes_deleted_when_all_safe_delete_fail(
        self,
        mock_select_files: MagicMock,
        mock_safe_delete: MagicMock,
        mock_fs: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test that if all deletions fail, 0 bytes are reported deleted."""
        caplog.set_level(logging.WARNING, logger=SUT_LOGGER_NAME)
        files_to_be_deleted = [FILE_1]
        mock_select_files.return_value = files_to_be_deleted

        mock_safe_delete.side_effect = DeleteValidationError("Failed for test")

        bytes_deleted = process_files_for_deletion(
            files_to_consider=SAMPLE_FILES_TO_CONSIDER,
            fs=mock_fs,
            directory_description=DIR_DESC,
            target_bytes_to_keep=0,
        )

        assert bytes_deleted == 0
        mock_safe_delete.assert_called_once_with(FILE_1.path, mock_fs)
        assert f"Could not delete file {FILE_1.path}" in caplog.text
        # No final deletion summary should be logged when nothing was deleted
        assert "Actually deleted" not in caplog.text
