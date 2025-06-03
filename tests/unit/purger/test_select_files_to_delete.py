from pathlib import Path
from typing import List

from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.purger.select_files_to_delete import (
    select_files_to_delete,
)  # Assuming select_files_to_delete is in this path


# Helper to create GatheredEntryData instances for tests
def _ged(name: str, mtime: float, size: int) -> GatheredEntryData:
    """Creates a GatheredEntryData instance."""
    return GatheredEntryData(mtime=mtime, size=size, path=Path(name))


# Sample files, sorted by mtime (oldest first)
FILE_OLDEST = _ged("oldest.dat", mtime=100.0, size=1000)
FILE_MID_1 = _ged("mid1.dat", mtime=200.0, size=500)
FILE_MID_2 = _ged("mid2.dat", mtime=300.0, size=2000)
FILE_NEWEST = _ged("newest.dat", mtime=400.0, size=200)

ALL_SAMPLE_FILES_SORTED: List[GatheredEntryData] = [
    FILE_OLDEST,
    FILE_MID_1,
    FILE_MID_2,
    FILE_NEWEST,
]
TOTAL_SIZE_ALL_SAMPLES = sum(
    f.size for f in ALL_SAMPLE_FILES_SORTED
)  # 1000 + 500 + 2000 + 200 = 3700


class TestSelectFilesToDelete:
    def test_no_deletion_needed_target_met(self):
        """Target disk usage is already met or exceeded."""
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,  # 3700
            target_bytes_to_keep=TOTAL_SIZE_ALL_SAMPLES
            + 100,  # Target 3800, current 3700
        )
        assert files_to_delete == []

    def test_no_deletion_needed_target_exactly_met(self):
        """Target disk usage is exactly met."""
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,  # 3700
            target_bytes_to_keep=TOTAL_SIZE_ALL_SAMPLES,  # Target 3700
        )
        assert files_to_delete == []

    def test_empty_file_list(self):
        """No files available to delete."""
        files_to_delete = select_files_to_delete(
            all_files=[],
            current_total_size=0,
            target_bytes_to_keep=100,  # Doesn't matter, no files
        )
        assert files_to_delete == []

    def test_empty_file_list_but_deletion_theoretically_needed(self):
        """No files available, even if current size exceeds target."""
        files_to_delete = select_files_to_delete(
            all_files=[],
            current_total_size=1000,  # Current 1000
            target_bytes_to_keep=100,  # Target 100, need to delete 900
        )
        assert files_to_delete == []  # But no files to delete

    def test_delete_one_file_to_meet_target_exactly(self):
        """Delete the oldest file, exactly meeting the target reduction."""
        # current_total_size = 3700
        # FILE_OLDEST.size = 1000
        # target_bytes_to_keep = 3700 - 1000 = 2700
        # bytes_to_delete = 3700 - 2700 = 1000
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,
            target_bytes_to_keep=TOTAL_SIZE_ALL_SAMPLES - FILE_OLDEST.size,
        )
        assert files_to_delete == [FILE_OLDEST]

    def test_delete_one_file_overshoots_target(self):
        """Delete oldest file, which frees more space than strictly needed."""
        # current_total_size = 3700
        # FILE_OLDEST.size = 1000
        # Need to delete 500 bytes. target_bytes_to_keep = 3700 - 500 = 3200
        # bytes_to_delete = 3700 - 3200 = 500
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,
            target_bytes_to_keep=TOTAL_SIZE_ALL_SAMPLES - (FILE_OLDEST.size // 2),
        )
        assert files_to_delete == [FILE_OLDEST]  # Still delete the whole oldest file

    def test_delete_multiple_files_to_meet_target(self):
        """Delete two oldest files to meet the target."""
        # current_total_size = 3700
        # FILE_OLDEST.size = 1000, FILE_MID_1.size = 500. Sum = 1500
        # target_bytes_to_keep = 3700 - 1500 = 2200
        # bytes_to_delete = 1500
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,
            target_bytes_to_keep=TOTAL_SIZE_ALL_SAMPLES
            - (FILE_OLDEST.size + FILE_MID_1.size),
        )
        assert files_to_delete == [FILE_OLDEST, FILE_MID_1]

    def test_delete_multiple_files_overshoots_target_slightly(self):
        """Delete two oldest files, slightly overshooting needed deletion."""
        # current_total_size = 3700
        # FILE_OLDEST.size = 1000, FILE_MID_1.size = 500. Sum = 1500
        # Need to delete 1400 bytes. target_bytes_to_keep = 3700 - 1400 = 2300
        # bytes_to_delete = 1400
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,
            target_bytes_to_keep=TOTAL_SIZE_ALL_SAMPLES
            - (FILE_OLDEST.size + FILE_MID_1.size - 100),
        )
        assert files_to_delete == [FILE_OLDEST, FILE_MID_1]

    def test_delete_all_files(self):
        """All files need to be deleted to try to meet target (target is 0)."""
        # current_total_size = 3700
        # target_bytes_to_keep = 0
        # bytes_to_delete = 3700
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,
            target_bytes_to_keep=0,
        )
        assert files_to_delete == ALL_SAMPLE_FILES_SORTED

    def test_delete_all_files_target_very_low(self):
        """All files need to be deleted (target less than smallest file size)."""
        # current_total_size = 3700
        # target_bytes_to_keep = 100 (less than any file size)
        # bytes_to_delete = 3600
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,
            target_bytes_to_keep=100,
        )
        assert (
            files_to_delete == ALL_SAMPLE_FILES_SORTED
        )  # Deletes all, as 3600 > sum of first three (3500)

    def test_target_bytes_to_keep_is_negative(self):
        """
        If target_bytes_to_keep is negative, bytes_to_delete will be
        current_total_size + abs(target_bytes_to_keep).
        Effectively means delete everything plus more, so delete all.
        """
        # current_total_size = 3700
        # target_bytes_to_keep = -100
        # bytes_to_delete = 3700 - (-100) = 3800
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,
            target_bytes_to_keep=-100,
        )
        assert files_to_delete == ALL_SAMPLE_FILES_SORTED

    def test_single_file_list_delete_it(self):
        """Only one file, and it needs to be deleted."""
        single_file_list = [FILE_OLDEST]
        current_size = FILE_OLDEST.size  # 1000
        target_keep = current_size - 100  # 900
        # bytes_to_delete = 100
        files_to_delete = select_files_to_delete(
            all_files=single_file_list,
            current_total_size=current_size,
            target_bytes_to_keep=target_keep,
        )
        assert files_to_delete == [FILE_OLDEST]

    def test_single_file_list_dont_delete_it(self):
        """Only one file, and it doesn't need to be deleted."""
        single_file_list = [FILE_OLDEST]
        current_size = FILE_OLDEST.size  # 1000
        target_keep = current_size  # 1000
        files_to_delete = select_files_to_delete(
            all_files=single_file_list,
            current_total_size=current_size,
            target_bytes_to_keep=target_keep,
        )
        assert files_to_delete == []

    def test_order_of_returned_files_is_preserved(self):
        """The returned list of files should maintain the input order (oldest first)."""
        # This is implicitly tested by other tests comparing lists, but an explicit one is fine.
        # current_total_size = 3700
        # target_bytes_to_keep = 2000
        # bytes_to_delete = 1700
        # Expected: FILE_OLDEST (1000), FILE_MID_1 (500). Sum=1500. Need more.
        # Add FILE_MID_2 (2000). Sum = 1000+500+2000 = 3500. This is >= 1700.
        # Wait, logic is:
        # bytes_to_delete = 3700 - 2000 = 1700
        # 1. FILE_OLDEST (1000). deleted_size = 1000. 1000 < 1700.
        # 2. FILE_MID_1 (500). deleted_size = 1000+500=1500. 1500 < 1700.
        # 3. FILE_MID_2 (2000). deleted_size = 1500+2000=3500. 3500 >= 1700. Stop.
        # Expected: [FILE_OLDEST, FILE_MID_1, FILE_MID_2]
        files_to_delete = select_files_to_delete(
            all_files=ALL_SAMPLE_FILES_SORTED,
            current_total_size=TOTAL_SIZE_ALL_SAMPLES,
            target_bytes_to_keep=2000,
        )
        assert files_to_delete == [FILE_OLDEST, FILE_MID_1, FILE_MID_2]
        # Verify individual elements if strict order matters beyond list equality
        assert files_to_delete[0] == FILE_OLDEST
        assert files_to_delete[1] == FILE_MID_1
        assert files_to_delete[2] == FILE_MID_2
