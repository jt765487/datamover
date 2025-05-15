import time
from pathlib import Path

import pytest

# --- Helper Data Structures (ensure these match your actual definitions) ---
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.scanner.file_state_record import (
    FileStateRecord,
    is_active_since_last_scan,
)

# --- Test Target ---
from datamover.scanner.update_file_state_record import update_file_state_record


# --- Fixtures ---


@pytest.fixture
def sample_paths() -> dict:
    """Provides a dictionary of sample Path objects for consistent use."""
    base = Path("/test/scan_dir")
    return {
        "file1": base / "file1.dat",
        "file2": base / "file2.dat",
        "file3_new": base / "file3_new.dat",
        "file4_also_new": base / "file4_also_new.dat",
    }


@pytest.fixture
def current_monotonic_time() -> float:
    """Provides a sample current monotonic time."""
    return (
        time.monotonic()
    )  # Use real time for simplicity, or mock if strict control needed


# --- Test Class ---


class TestUpdateFileStateRecord:
    """
    Tests for the `update_file_state_record` function, which is responsible
    for generating new file states based on current scan data and previous states.
    """

    def test_empty_initial_and_empty_gathered(self, current_monotonic_time: float):
        """
        Scenario: No existing files and no files gathered in the current scan.
        Expected: Empty new states and empty removed paths.
        """
        existing_states: dict[Path, FileStateRecord] = {}
        gathered_data: list[GatheredEntryData] = []
        mono_now = current_monotonic_time

        next_states, removed_paths = update_file_state_record(
            existing_states, gathered_data, mono_now
        )

        assert next_states == {}
        assert removed_paths == set()

    def test_empty_initial_new_files_gathered(
        self, sample_paths: dict, current_monotonic_time: float
    ):
        """
        Scenario: No existing files, but new files are found in the current scan.
        Expected: All gathered files appear in `next_states` as new records.
                  `removed_paths` should be empty.
                  `first_seen_mono` should be `monotonic_time_now`.
                  `prev_scan_size` and `prev_scan_mtime_wall` should match current values.
        """
        existing_states: dict[Path, FileStateRecord] = {}
        mono_now = current_monotonic_time
        wall_time_now = time.time()  # For mtimes

        gathered_items: list[GatheredEntryData] = [
            GatheredEntryData(
                path=sample_paths["file1"], size=100, mtime=wall_time_now - 10
            ),
            GatheredEntryData(
                path=sample_paths["file2"], size=200, mtime=wall_time_now - 5
            ),
        ]

        next_states, removed_paths = update_file_state_record(
            existing_states, gathered_items, mono_now
        )

        assert len(next_states) == 2
        assert removed_paths == set()

        # Check file1
        f1_state = next_states[sample_paths["file1"]]
        assert f1_state.path == sample_paths["file1"]
        assert f1_state.size == 100
        assert f1_state.mtime_wall == wall_time_now - 10
        assert f1_state.first_seen_mono == mono_now
        assert f1_state.prev_scan_size == 100  # Initialized to current
        assert (
            f1_state.prev_scan_mtime_wall == wall_time_now - 10
        )  # Initialized to current
        assert not is_active_since_last_scan(
            f1_state
        )  # Should not be active on first sight

        # Check file2
        f2_state = next_states[sample_paths["file2"]]
        assert f2_state.path == sample_paths["file2"]
        assert f2_state.size == 200
        assert f2_state.mtime_wall == wall_time_now - 5
        assert f2_state.first_seen_mono == mono_now
        assert f2_state.prev_scan_size == 200  # Initialized to current
        assert (
            f2_state.prev_scan_mtime_wall == wall_time_now - 5
        )  # Initialized to current
        assert not is_active_since_last_scan(f2_state)

    def test_existing_files_none_gathered(
        self, sample_paths: dict, current_monotonic_time: float
    ):
        """
        Scenario: Existing files were tracked, but no files are found in the current scan.
        Expected: `next_states` should be empty.
                  All previously existing files should be in `removed_paths`.
        """
        mono_now = current_monotonic_time
        wall_time_now = time.time()

        existing_states: dict[Path, FileStateRecord] = {
            sample_paths["file1"]: FileStateRecord(
                path=sample_paths["file1"],
                size=50,
                mtime_wall=wall_time_now - 20,
                first_seen_mono=mono_now - 100,
                prev_scan_size=50,
                prev_scan_mtime_wall=wall_time_now - 20,
            ),
            sample_paths["file2"]: FileStateRecord(
                path=sample_paths["file2"],
                size=150,
                mtime_wall=wall_time_now - 30,
                first_seen_mono=mono_now - 100,
                prev_scan_size=150,
                prev_scan_mtime_wall=wall_time_now - 30,
            ),
        }
        gathered_data: list[GatheredEntryData] = []

        next_states, removed_paths = update_file_state_record(
            existing_states, gathered_data, mono_now
        )

        assert next_states == {}
        assert removed_paths == {sample_paths["file1"], sample_paths["file2"]}

    def test_mixed_scenario_update_new_remove(
        self, sample_paths: dict, current_monotonic_time: float
    ):
        """
        Scenario: A mix of existing files (some updated, some not found) and new files.
        Expected: Correct updates, new additions, and removals.
        """
        mono_now = current_monotonic_time
        wall_time_now = time.time()

        # Existing state for file1 (will be updated) and file2 (will be removed)
        # file1 initial state
        p1 = sample_paths["file1"]
        p1_first_seen = mono_now - 200
        p1_old_size = 100
        p1_old_mtime = wall_time_now - 100
        existing_states: dict[Path, FileStateRecord] = {
            p1: FileStateRecord(
                path=p1,
                size=p1_old_size,
                mtime_wall=p1_old_mtime,
                first_seen_mono=p1_first_seen,
                prev_scan_size=p1_old_size - 10,  # some previous prev
                prev_scan_mtime_wall=p1_old_mtime - 10,  # some previous prev
            ),
            sample_paths["file2"]: FileStateRecord(  # This file will be "removed"
                path=sample_paths["file2"],
                size=200,
                mtime_wall=wall_time_now - 50,
                first_seen_mono=mono_now - 150,
                prev_scan_size=200,
                prev_scan_mtime_wall=wall_time_now - 50,
            ),
        }

        # Gathered data: file1 (updated), file3_new (new)
        p1_new_size = 150  # file1 size changed
        p1_new_mtime = wall_time_now - 10  # file1 mtime changed
        gathered_items: list[GatheredEntryData] = [
            GatheredEntryData(path=p1, size=p1_new_size, mtime=p1_new_mtime),
            GatheredEntryData(
                path=sample_paths["file3_new"], size=300, mtime=wall_time_now - 5
            ),
        ]

        next_states, removed_paths = update_file_state_record(
            existing_states, gathered_items, mono_now
        )

        # --- Assertions ---
        assert len(next_states) == 2  # file1 (updated) + file3_new (new)
        assert removed_paths == {sample_paths["file2"]}

        # Check updated file1
        assert p1 in next_states
        f1_updated_state = next_states[p1]
        assert f1_updated_state.path == p1
        assert f1_updated_state.size == p1_new_size
        assert f1_updated_state.mtime_wall == p1_new_mtime
        assert f1_updated_state.first_seen_mono == p1_first_seen  # Preserved
        assert f1_updated_state.prev_scan_size == p1_old_size  # From old_state.size
        assert (
            f1_updated_state.prev_scan_mtime_wall == p1_old_mtime
        )  # From old_state.mtime_wall
        assert is_active_since_last_scan(f1_updated_state)  # Should be active

        # Check new file3_new
        p3 = sample_paths["file3_new"]
        assert p3 in next_states
        f3_new_state = next_states[p3]
        assert f3_new_state.path == p3
        assert f3_new_state.size == 300
        assert f3_new_state.mtime_wall == wall_time_now - 5
        assert f3_new_state.first_seen_mono == mono_now  # New timestamp
        assert f3_new_state.prev_scan_size == 300  # Initialized to current
        assert (
            f3_new_state.prev_scan_mtime_wall == wall_time_now - 5
        )  # Initialized to current
        assert not is_active_since_last_scan(f3_new_state)  # Not active on first sight

    def test_input_state_immutability(
        self, sample_paths: dict, current_monotonic_time: float
    ):
        """
        Verifies that the input `existing_file_states` dictionary is not modified
        by the function.
        """
        mono_now = current_monotonic_time
        wall_time_now = time.time()

        p1 = sample_paths["file1"]
        original_record = FileStateRecord(
            path=p1,
            size=100,
            mtime_wall=wall_time_now - 20,
            first_seen_mono=mono_now - 100,
            prev_scan_size=100,
            prev_scan_mtime_wall=wall_time_now - 20,
        )
        existing_states: dict[Path, FileStateRecord] = {p1: original_record}
        # Make a copy for comparison
        existing_states_copy = existing_states.copy()

        gathered_items: list[GatheredEntryData] = [
            GatheredEntryData(
                path=p1, size=150, mtime=wall_time_now - 10
            ),  # Update file1
        ]

        update_file_state_record(existing_states, gathered_items, mono_now)

        # Assert original dictionary is unchanged
        assert existing_states == existing_states_copy
        # Also, check if the record object itself (if it was mutable) was changed,
        # but FileStateRecord is frozen, so this is less of a concern for the record.
        # The primary check here is that the dictionary existing_states is not mutated.
        assert (
            existing_states[p1] is original_record
        )  # Object identity check for the record
