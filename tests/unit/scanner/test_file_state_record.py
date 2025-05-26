import time
import pytest
from pathlib import Path
from dataclasses import FrozenInstanceError

# --- Test Target ---
from datamover.scanner.file_state_record import (
    FileStateRecord,
    is_file_lost,
    is_active_since_last_scan,
    is_file_present_too_long,
)

# --- Fixtures ---


@pytest.fixture
def sample_path() -> Path:
    """Provides a sample Path object for tests."""
    return Path("/test/dir/sample_file.dat")


@pytest.fixture
def current_times() -> dict:
    """Provides current wall and monotonic times."""
    return {"wall": time.time(), "mono": time.monotonic()}


# --- Tests for FileStateRecord ---


class TestFileStateRecord:
    def test_creation_and_attributes(self, sample_path, current_times):
        # Arrange
        path = sample_path
        size = 1024
        mtime = current_times["wall"] - 10.0
        first_seen = current_times["mono"] - 100.0
        prev_size = 512
        prev_mtime = mtime - 20.0

        # Act
        record = FileStateRecord(
            path=path,
            size=size,
            mtime_wall=mtime,
            first_seen_mono=first_seen,
            prev_scan_size=prev_size,
            prev_scan_mtime_wall=prev_mtime,
        )

        # Assert
        assert record.path == path
        assert record.size == size
        assert record.mtime_wall == mtime
        assert record.first_seen_mono == first_seen
        assert record.prev_scan_size == prev_size
        assert record.prev_scan_mtime_wall == prev_mtime

    def test_is_frozen(self, sample_path, current_times):
        record = FileStateRecord(
            path=sample_path,
            size=100,
            mtime_wall=current_times["wall"],
            first_seen_mono=current_times["mono"],
            prev_scan_size=100,
            prev_scan_mtime_wall=current_times["wall"],
        )
        with pytest.raises(FrozenInstanceError):
            record.size = 200
        with pytest.raises(FrozenInstanceError):
            record.path = Path("/new/path")


# --- Tests for is_file_lost ---


@pytest.mark.parametrize(
    "mtime_offset, check_offset, timeout, expected",
    [
        (-30, 0, 20, True),  # lost
        (-15, 0, 20, False),  # not lost
        (-20, 0, 20, False),  # boundary
        (-20.001, 0, 20, True),  # just over
        (0, 0, 0, False),  # no timeout
        (-1, 0, 0, True),  # zero timeout
        (-10, -5, 20, False),  # check earlier not lost
        (-10, 15, 20, True),  # check later becomes lost
        (-10, 0, -5, True),  # negative timeout
        (-10, -15, 20, False),  # check before mtime
    ],
)
def test_is_file_lost(
    mtime_offset, check_offset, timeout, expected, sample_path, current_times
):
    base_wall = current_times["wall"]
    mtime = base_wall + mtime_offset
    check_time = base_wall + check_offset
    record = FileStateRecord(
        path=sample_path,
        size=0,
        mtime_wall=mtime,
        first_seen_mono=current_times["mono"],
        prev_scan_size=0,
        prev_scan_mtime_wall=mtime,
    )
    assert is_file_lost(record, check_time, timeout) is expected


# --- Tests for is_active_since_last_scan ---


@pytest.mark.parametrize(
    "cur_size, cur_moff, prev_size, prev_moff, expected",
    [
        (100, 0, 50, 0, True),  # size changed
        (100, 10, 100, 0, True),  # mtime changed
        (100, 5, 95, 3, True),  # both changed
        (100, 0, 100, 0, False),  # no change
        (0, 0, 0, 0, False),  # both zero
    ],
)
def test_is_active_since_last_scan(
    cur_size, cur_moff, prev_size, prev_moff, expected, sample_path, current_times
):
    now_wall = current_times["wall"]
    record = FileStateRecord(
        path=sample_path,
        size=cur_size,
        mtime_wall=now_wall + cur_moff,
        first_seen_mono=current_times["mono"],
        prev_scan_size=prev_size,
        prev_scan_mtime_wall=now_wall + prev_moff,
    )
    assert is_active_since_last_scan(record) is expected


# --- Tests for is_file_present_too_long ---


@pytest.mark.parametrize(
    "seen_offset, check_offset, timeout, expected",
    [
        (-30, 0, 20, True),  # too long
        (-15, 0, 20, False),  # recent
        (-20, 0, 20, False),  # boundary
        (-20.001, 0, 20, True),  # just over
        (0, 0, 0, False),  # timeout zero
        (-1, 0, 0, True),  # seen before zero timeout
        (-10, -5, 20, False),  # check earlier not too long
        (-10, 15, 20, True),  # check later becomes too long
        (-10, 0, -5, True),  # negative timeout
        (-10, -15, 20, False),  # check before seen
    ],
)
def test_is_file_present_too_long(
    seen_offset, check_offset, timeout, expected, sample_path, current_times
):
    now_mono = current_times["mono"]
    first_seen = now_mono + seen_offset
    check_time = now_mono + check_offset
    record = FileStateRecord(
        path=sample_path,
        size=0,
        mtime_wall=current_times["wall"],
        first_seen_mono=first_seen,
        prev_scan_size=0,
        prev_scan_mtime_wall=current_times["wall"],
    )
    assert is_file_present_too_long(record, check_time, timeout) is expected
