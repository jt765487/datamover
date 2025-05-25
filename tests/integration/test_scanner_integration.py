import logging
import os
import queue
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from datamover.file_functions.fs_mock import FS
from datamover.scanner.do_single_cycle import DoSingleCycle
from datamover.scanner.file_state_record import FileStateRecord
from tests.test_utils.fs_helpers import create_and_stamp_real_fs


# --- Test Config & Helpers ---
@dataclass(frozen=True)
class ScannerTimeouts:
    lost: float = 0.3
    stuck_active: float = 0.5
    cycle_step: float = 0.1


SCANNER_TIMEOUTS = ScannerTimeouts()


EXTENSION = "pcap"
FILE_SIZE_1 = 1024
FILE_SIZE_2 = 2048

PROCESSOR_LOGGER_NAME = "datamover.scanner.do_single_cycle"
RESULTS_LOGGER_NAME = "datamover.scanner.process_scan_results"
REPORTING_LOGGER_NAME = "datamover.scanner.scan_reporting"
FILTER_LOGGER_NAME = "datamover.file_functions.scan_directory_and_filter"
test_module_logger = logging.getLogger(__name__)


# --- Fixtures ---
@pytest.fixture
def integration_scan_dir(tmp_path: Path) -> Path:
    scan_dir = tmp_path / "scanner_integration_data"
    scan_dir.mkdir(parents=True, exist_ok=True)
    return scan_dir

@pytest.fixture
def integration_csv_restart_dir(tmp_path: Path) -> Path:
    """Provides a temporary directory for CSV restart files for integration tests."""
    csv_dir = tmp_path / "scanner_integration_csv_restart"
    csv_dir.mkdir(parents=True, exist_ok=True)
    return csv_dir

@pytest.fixture
def real_lost_queue() -> queue.Queue:
    return queue.Queue()


@pytest.fixture
def mock_safe_put_integration(mocker) -> MagicMock:
    return mocker.patch("datamover.scanner.do_single_cycle.safe_put", autospec=True)


@pytest.fixture
def mock_report_changes_integration(mocker) -> MagicMock:
    return mocker.patch(
        "datamover.scanner.do_single_cycle.report_state_changes", autospec=True
    )


@pytest.fixture
def integration_processor(
    integration_scan_dir: Path,
    integration_csv_restart_dir: Path,
    real_fs: FS,
    real_lost_queue: queue.Queue,
) -> DoSingleCycle:
    return DoSingleCycle(
        validated_directory_to_scan=integration_scan_dir,
        csv_restart_directory=integration_csv_restart_dir,
        extension_to_scan_no_dot=EXTENSION,
        lost_timeout=SCANNER_TIMEOUTS.lost,
        stuck_active_file_timeout=SCANNER_TIMEOUTS.stuck_active,
        lost_file_queue=real_lost_queue,
        time_func=time.time,
        monotonic_func=time.monotonic,
        fs=real_fs,
    )


@pytest.fixture
def caplog_debug_all(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    return caplog


# --- Integration Tests ---
@pytest.mark.integration
class TestScannerIntegration:
    def test_first_cycle_on_empty_directory(
        self,
        integration_processor: DoSingleCycle,
        mock_safe_put_integration: MagicMock,
        caplog_debug_all: pytest.LogCaptureFixture,
        request: pytest.FixtureRequest,
    ):
        state, lost, stuck = integration_processor.process_one_cycle({}, set(), set())
        assert state == {}
        assert lost == set()
        assert stuck == set()
        mock_safe_put_integration.assert_not_called()
        assert any(
            r.name == PROCESSOR_LOGGER_NAME
            and r.levelname == "DEBUG"
            and "Scan found 0 files matching" in r.message
            for r in caplog_debug_all.records
        ), f"Expected 'Scan found 0 files...' log. Got:\n{caplog_debug_all.text}"

    def test_first_cycle_with_single_file(
        self,
        integration_processor: DoSingleCycle,
        real_fs: FS,
        mock_safe_put_integration: MagicMock,
        caplog_debug_all: pytest.LogCaptureFixture,
    ):
        processor = integration_processor
        scan_dir = processor.directory_to_scan
        file_path = scan_dir / f"file_A.{EXTENSION}"
        mtime = time.time() - 0.2
        create_and_stamp_real_fs(real_fs, file_path, FILE_SIZE_1, mtime)
        mono_before = time.monotonic()
        state, lost, stuck = processor.process_one_cycle({}, set(), set())
        mono_after = time.monotonic()
        assert file_path in state
        rec = state[file_path]
        assert rec.size == FILE_SIZE_1
        assert rec.prev_scan_size == FILE_SIZE_1
        assert pytest.approx(rec.mtime_wall, abs=0.1) == mtime
        assert mono_before <= rec.first_seen_mono <= mono_after
        assert lost == set() and stuck == set()
        mock_safe_put_integration.assert_not_called()
        assert any(
            r.name == PROCESSOR_LOGGER_NAME
            and r.levelname == "DEBUG"
            and "Scan found 1 files matching" in r.message
            for r in caplog_debug_all.records
        ), "Expected 'Scan found 1 files...' log."

    def test_cycle_detects_lost_stale_file(
        self,
        integration_processor: DoSingleCycle,
        real_fs: FS,
        mock_safe_put_integration: MagicMock,
        real_lost_queue: queue.Queue,
    ):
        processor = integration_processor
        scan_dir = processor.directory_to_scan
        file_path = scan_dir / f"stale_file.{EXTENSION}"
        create_and_stamp_real_fs(real_fs, file_path, FILE_SIZE_1, time.time() - 0.2)
        state1, lost1, stuck1 = processor.process_one_cycle({}, set(), set())
        assert file_path in state1 and lost1 == set()
        mock_safe_put_integration.assert_not_called()
        time.sleep(SCANNER_TIMEOUTS.lost + SCANNER_TIMEOUTS.cycle_step)
        state2, lost2, stuck2 = processor.process_one_cycle(state1, lost1, stuck1)
        assert file_path in lost2 and stuck2 == set()
        mock_safe_put_integration.assert_called_once_with(
            item=file_path,
            output_queue=real_lost_queue,
            queue_name=processor.lost_queue_name,
        )

    def test_cycle_detects_stuck_active_file(
        self,
        integration_processor: DoSingleCycle,
        real_fs: FS,
        mock_report_changes_integration: MagicMock,
    ):
        processor = integration_processor
        scan_dir = processor.directory_to_scan
        file_path = scan_dir / f"active_stuck.{EXTENSION}"
        state, lost, stuck = {}, set(), set()
        reported = False
        cycles = int(SCANNER_TIMEOUTS.stuck_active / SCANNER_TIMEOUTS.cycle_step) + 2
        for i in range(cycles):
            create_and_stamp_real_fs(
                real_fs,
                file_path,
                FILE_SIZE_1 + i * 10,
                time.time() - 0.05,
                initial_create=(i == 0),
            )
            state, lost, stuck = processor.process_one_cycle(state, lost, stuck)
            if i == 0:
                first_seen = state[file_path].first_seen_mono
            elapsed = time.monotonic() - first_seen
            if elapsed > SCANNER_TIMEOUTS.stuck_active and not reported:
                assert file_path in stuck
                assert any(
                    call.kwargs.get("newly_stuck_active_paths") == {file_path}
                    for call in mock_report_changes_integration.call_args_list[-1:]
                ), "Expected report_state_changes for newly stuck"
                reported = True
            time.sleep(SCANNER_TIMEOUTS.cycle_step)
        assert reported, "File never reported as stuck"

    def test_previously_stuck_file_transitions_to_lost(
        self,
        integration_processor: DoSingleCycle,
        real_fs: FS,
        mock_safe_put_integration: MagicMock,
        real_lost_queue: queue.Queue,
        mock_report_changes_integration: MagicMock,
    ):
        processor = integration_processor
        file_path = processor.directory_to_scan / f"stuck_to_lost.{EXTENSION}"
        state, lost, stuck = {}, set(), set()
        # Phase 1: make stuck
        for i in range(
            int(SCANNER_TIMEOUTS.stuck_active / SCANNER_TIMEOUTS.cycle_step) + 2
        ):
            create_and_stamp_real_fs(
                real_fs,
                file_path,
                FILE_SIZE_1,
                time.time() - 0.05,
                initial_create=(i == 0),
            )
            state, lost, stuck = processor.process_one_cycle(state, lost, stuck)
            time.sleep(SCANNER_TIMEOUTS.cycle_step)
        assert file_path in stuck
        mock_report_changes_integration.reset_mock()
        mock_safe_put_integration.reset_mock()
        # Phase 2: transition to lost
        for _ in range(int(SCANNER_TIMEOUTS.lost / SCANNER_TIMEOUTS.cycle_step) + 2):
            state, lost, stuck = processor.process_one_cycle(state, lost, stuck)
            if file_path in lost:
                mock_safe_put_integration.assert_called_once_with(
                    item=file_path,
                    output_queue=real_lost_queue,
                    queue_name=processor.lost_queue_name,
                )
                assert any(
                    call.kwargs.get("newly_lost_paths") == {file_path}
                    for call in mock_report_changes_integration.call_args_list
                ), "Expected report_state_changes for newly lost"
                break
            time.sleep(SCANNER_TIMEOUTS.cycle_step)
        else:
            pytest.fail("File did not transition to LOST in expected cycles")

    def test_ignores_non_matching_extension(
        self,
        integration_processor: DoSingleCycle,
        real_fs: FS,
        mock_safe_put_integration: MagicMock,
        caplog_debug_all: pytest.LogCaptureFixture,
    ):
        processor = integration_processor
        scan_dir = processor.directory_to_scan
        good = scan_dir / f"good.{EXTENSION}"
        bad = scan_dir / "other.txt"
        create_and_stamp_real_fs(real_fs, good, FILE_SIZE_1, time.time() - 0.1)
        create_and_stamp_real_fs(real_fs, bad, FILE_SIZE_2, time.time() - 0.1)
        state, lost, stuck = processor.process_one_cycle({}, set(), set())
        assert good in state and bad not in state
        mock_safe_put_integration.assert_not_called()
        assert any(
            r.name == PROCESSOR_LOGGER_NAME
            and r.levelname == "DEBUG"
            and f"Scan found 1 files matching '.{EXTENSION}'" in r.message
            for r in caplog_debug_all.records
        ), "Expected scan log for single matching file"

    def test_disappeared_file_is_removed_not_lost(
        self,
        integration_processor: DoSingleCycle,
        real_fs: FS,
        mock_safe_put_integration: MagicMock,
        mock_report_changes_integration: MagicMock,
    ):
        processor = integration_processor
        ghost = processor.directory_to_scan / f"ghost.{EXTENSION}"
        prev_state: dict[Path, FileStateRecord] = {
            ghost: FileStateRecord(
                path=ghost,
                size=0,
                mtime_wall=time.time() - 100,
                first_seen_mono=time.monotonic() - 100,
                prev_scan_size=0,
                prev_scan_mtime_wall=time.time() - 100,
            )
        }
        if real_fs.exists(ghost):
            os.remove(str(ghost))
        state, lost, stuck = processor.process_one_cycle(prev_state, set(), set())
        assert ghost not in state
        mock_safe_put_integration.assert_not_called()
        mock_report_changes_integration.assert_called_once()
        kwargs = mock_report_changes_integration.call_args.kwargs
        assert kwargs.get("removed_tracking_paths") == {ghost}
        assert kwargs.get("newly_lost_paths") == set()
        assert kwargs.get("newly_stuck_active_paths") == set()

    def test_lost_file_stays_lost_and_not_re_queued(
        self,
        integration_processor: DoSingleCycle,
        real_fs: FS,
        real_lost_queue: queue.Queue,
        mock_safe_put_integration: MagicMock,
        mock_report_changes_integration: MagicMock,
    ):
        processor = integration_processor
        path = processor.directory_to_scan / f"persistent_lost.{EXTENSION}"
        # Cycle 1
        create_and_stamp_real_fs(real_fs, path, FILE_SIZE_1, time.time() - 0.2)
        state1, lost1, stuck1 = processor.process_one_cycle({}, set(), set())
        mock_safe_put_integration.assert_not_called()
        mock_report_changes_integration.reset_mock()
        # Cycle 2: become lost
        time.sleep(SCANNER_TIMEOUTS.lost + SCANNER_TIMEOUTS.cycle_step)
        state2, lost2, stuck2 = processor.process_one_cycle(state1, lost1, stuck1)
        assert path in lost2
        mock_safe_put_integration.assert_called_once()
        mock_report_changes_integration.reset_mock()
        mock_safe_put_integration.reset_mock()
        # Cycle 3: stays lost
        time.sleep(SCANNER_TIMEOUTS.cycle_step)
        state3, lost3, stuck3 = processor.process_one_cycle(state2, lost2, stuck2)
        assert path in lost3
        mock_safe_put_integration.assert_not_called()
        last = mock_report_changes_integration.call_args_list[-1]
        assert last.kwargs.get("newly_lost_paths") == set()
