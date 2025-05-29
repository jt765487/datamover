"""
Global pytest fixtures for the DataMover application test suite.

This file provides:
- Foundational fixtures for test environments (temporary directories, real filesystem access).
- Default configurations (both real and mocked) for the application.
- Generic mock objects for common application protocolpiks and dependencies.
- Setup fixtures for unit-testing specific components like RetryableFileSender.
"""

import logging
import threading
from pathlib import Path
from typing import NamedTuple, Any
from unittest.mock import Mock, MagicMock

import pytest

# --- Project-specific Imports ---
from datamover.file_functions.fs_mock import FS as ConcreteFSImpl
from datamover.protocols import FS as FSProtocol, HttpClient, SafeFileMover
from datamover.startup_code.load_config import Config

logger = logging.getLogger(__name__)


# --- 1. Foundational Test Environment Fixtures ---


class StandardTestDirs(NamedTuple):
    """
    A structure to hold paths to standard temporary directories used in tests.
    All paths are absolute, residing within a unique pytest tmp_path.
    """

    base_dir: Path  # Root directory for this test environment setup
    source_dir: Path  # Simulated source directory for data files
    worker_dir: Path  # Intermediate work/staging directory
    uploaded_dir: Path  # Directory for successfully uploaded files
    dead_letter_dir: Path  # Directory for terminally failed files
    csv_dir: Path  # Directory for CSV metadata files
    log_dir: Path  # Directory for test-specific application logs


@pytest.fixture(scope="function")
def real_fs() -> FSProtocol:  # Hinting with the protocol for consumers
    """
    Provides a real filesystem interface instance that interacts with the
    actual operating system's filesystem. Uses the concrete implementation.
    This is crucial for integration and black-box tests.
    Scope: function (a new instance per test function for isolation).
    """
    # ConcreteFSImpl is 'datamover.file_functions.fs_mock.FS'
    # This assumes fs_mock.FS is your actual, working FS implementation.
    return ConcreteFSImpl()


@pytest.fixture(scope="function")
def standard_test_dirs(tmp_path: Path, real_fs: FSProtocol) -> StandardTestDirs:
    """
    Creates and provides a standard set of temporary directories for testing.
    Uses the `real_fs` fixture to perform directory creation, ensuring that
    the same FS abstraction used by the application is used for setup.

    Scope: function (new set of directories for each test).
    """
    base = tmp_path / "test_app_env_root"
    logger.debug(f"Setting up standard test directories under: {base}")

    dirs = StandardTestDirs(
        base_dir=base,
        source_dir=base / "source_files",
        worker_dir=base / "worker_files",
        uploaded_dir=base / "uploaded_files",
        dead_letter_dir=base / "dead_letter_files",
        csv_dir=base / "csv_input_files",
        log_dir=base / "app_test_logs",
    )

    for dir_path in dirs:
        if isinstance(dir_path, Path):  # Ensure we only try to mkdir on Path objects
            logger.debug(f"Creating directory using real_fs: {dir_path}")
            real_fs.mkdir(dir_path, parents=True, exist_ok=True)

    return dirs


# --- 2. Configuration Fixtures ---


@pytest.fixture(scope="function")
def default_real_test_config(standard_test_dirs: StandardTestDirs) -> Config:
    """
    Provides a real, fully populated Config object with sensible defaults
    suitable for most integration and black-box tests. Uses paths from
    `standard_test_dirs`. Tests can inject this and then override specific
    fields if needed using `dataclasses.replace()`.

    Scope: function (new Config instance for each test).
    """
    logger.debug(
        f"Creating default real test Config using base_dir: {standard_test_dirs.base_dir}"
    )
    cfg = Config(
        base_dir=standard_test_dirs.base_dir,
        logger_dir=standard_test_dirs.log_dir,
        source_dir=standard_test_dirs.source_dir,
        worker_dir=standard_test_dirs.worker_dir,
        uploaded_dir=standard_test_dirs.uploaded_dir,
        dead_letter_dir=standard_test_dirs.dead_letter_dir,
        csv_dir=standard_test_dirs.csv_dir,
        pcap_extension_no_dot="pcap",
        csv_extension_no_dot="csv",
        move_poll_interval_seconds=0.1,  # Reasonably fast for tests
        scanner_check_seconds=0.2,  # Ditto; ensure 'scanner_check_seconds' matches Config class
        lost_timeout_seconds=0.5,  # Short for testing lost logic
        stuck_active_file_timeout_seconds=1.0,  # Must be > lost_timeout_seconds
        event_queue_poll_timeout_seconds=0.1,
        uploader_poll_interval_seconds=0.1,
        heartbeat_target_interval_s=3600.0,  # Effectively disable for most tests to reduce log noise
        remote_host_url="http://default-placeholder-nifi.test/api",  # Placeholder, override for HTTP tests
        request_timeout=5.0,  # Default network timeout for tests
        verify_ssl=False,  # Common for test environments
        initial_backoff=0.01,  # Fast backoff for retries
        max_backoff=0.1,  # Low max backoff
    )
    return cfg


@pytest.fixture
def mock_config(
    standard_test_dirs: StandardTestDirs,
) -> MagicMock:  # Now uses standard_test_dirs
    """
    Provides a MagicMock object that mimics the application's Config structure.
    Useful for unit tests requiring a Config object where specific attributes
    can be easily set and asserted, without involving real Config class logic
    (like __post_init__ validations or path derivations if any).

    The mock is configured with `spec=Config` to ensure it only allows
    attributes present on the real Config dataclass, catching typos.
    Paths are populated from `standard_test_dirs` for consistency.
    """
    logger.debug(
        f"Creating mock_config based on standard_test_dirs: {standard_test_dirs.base_dir}"
    )
    cfg = MagicMock(spec=Config)

    # Populate attributes to match the Config class structure
    # [Directories]
    cfg.base_dir = standard_test_dirs.base_dir
    cfg.logger_dir = standard_test_dirs.log_dir
    cfg.source_dir = standard_test_dirs.source_dir
    cfg.worker_dir = standard_test_dirs.worker_dir
    cfg.uploaded_dir = standard_test_dirs.uploaded_dir
    cfg.dead_letter_dir = standard_test_dirs.dead_letter_dir
    cfg.csv_dir = standard_test_dirs.csv_dir

    # [Files]
    cfg.pcap_extension_no_dot = "pcap"
    cfg.csv_extension_no_dot = "csv"

    # [Mover] - Default mock values, can be overridden in tests
    cfg.move_poll_interval_seconds = 1.0

    # [Scanner] - Default mock values
    # CRITICAL: Ensure 'scanner_check_seconds' matches your actual Config class attribute name.
    # Using 'scanner_check_seconds' here assuming it's the corrected name.
    cfg.scanner_check_seconds = 5.0
    cfg.lost_timeout_seconds = 30.0
    cfg.stuck_active_file_timeout_seconds = 60.0  # Must be > lost_timeout

    # [Tailer]
    cfg.event_queue_poll_timeout_seconds = 1.0

    # [Uploader]
    cfg.uploader_poll_interval_seconds = 0.5
    cfg.heartbeat_target_interval_s = 60.0
    cfg.remote_host_url = "http://mock-config.example.com/upload"
    cfg.request_timeout = 10.0
    cfg.verify_ssl = False  # Default for mocks
    cfg.initial_backoff = 0.1
    cfg.max_backoff = 1.0

    return cfg


# --- 3. Generic Mocking Fixtures for Protocols & Standard Components ---


@pytest.fixture
def mock_fs() -> MagicMock:  # unittest.mock.MagicMock
    """
    Provides a generic MagicMock for the FS (Filesystem) protocol.
    `spec=FSProtocol` ensures it adheres to the FS interface.
    Useful for unit tests to isolate from real filesystem interactions.
    """
    # Use FSProtocol to ensure the mock matches the interface definition
    return MagicMock(spec=FSProtocol, name="MockFS")


@pytest.fixture
def mock_fs_configured(mock_fs: MagicMock) -> MagicMock:
    """
    Provides an FS mock (based on `mock_fs`) where `exists` defaults to False.
    Useful for testing scenarios involving non-existent paths or creation logic.
    """
    mock_fs.exists = Mock(return_value=False, name="MockFSExistsFalse")
    return mock_fs


@pytest.fixture
def mock_http_client() -> MagicMock:  # unittest.mock.MagicMock
    """
    Provides a generic MagicMock for the HttpClient protocol.
    Allows testing components that make HTTP requests without actual network calls.
    The `post` method (and others if defined in HttpClient) will also be MagicMocks.
    """
    return MagicMock(spec=HttpClient, name="MockHttpClient")


@pytest.fixture
def mock_stop_event() -> MagicMock:  # unittest.mock.MagicMock
    """
    Provides a mock `threading.Event` object.
    `is_set` defaults to returning False.
    `wait` defaults to returning False (simulating no timeout/no event set).
    """
    evt = MagicMock(spec=threading.Event, name="MockStopEvent")
    evt.is_set.return_value = False
    evt.wait = Mock(return_value=False, name="MockStopEventWait")  # `wait` is a method
    return evt


@pytest.fixture
def mock_safe_file_mover() -> MagicMock:  # unittest.mock.MagicMock
    """
    Provides a generic MagicMock for the SafeFileMover protocol.
    Useful for testing components that delegate file moving operations.
    """
    return MagicMock(spec=SafeFileMover, name="MockSafeFileMover")


# --- 4. Specific Component Unit Test Setup Fixtures ---


@pytest.fixture
def mock_fs_for_sender_unit_tests(mock_fs: MagicMock) -> MagicMock:
    """
    Configures the generic `mock_fs` specifically for unit testing RetryableFileSender.
    Mocks the `open` method to return a context manager with a mock file handle,
    which is often needed when testing file sending logic.
    """
    logger.debug("Configuring mock_fs for sender unit tests (mocked open context).")
    mock_file_handle = MagicMock(name="UnitSenderMockFileHandle")
    # Simulate read() returning some default bytes or make it configurable if tests need varying content
    mock_file_handle.read.return_value = b"mocked file content for sender"

    mock_context_manager = MagicMock(name="UnitSenderMockFileContextManager")
    mock_context_manager.__enter__.return_value = mock_file_handle
    mock_context_manager.__exit__.return_value = (
        None  # Standard for context manager exit
    )

    mock_fs.open = Mock(return_value=mock_context_manager, name="UnitSenderMockFsOpen")

    # Ensure other commonly used FS methods are present on the mock_fs if needed by sender
    # Their behavior (return_value, side_effect) can be set per-test.
    if not hasattr(mock_fs, "exists"):  # Should already exist due to spec=FSProtocol
        mock_fs.exists = Mock(name="UnitSenderMockFsExists")
    if not hasattr(mock_fs, "stat"):
        mock_fs.stat = Mock(name="UnitSenderMockFsStat")

    return mock_fs


@pytest.fixture
def retryable_sender_unit_test_deps(  # Renamed from 'sender' for clarity
    mock_config: MagicMock,  # Uses the MagicMock version of Config
    mock_http_client: MagicMock,
    mock_fs_for_sender_unit_tests: MagicMock,  # Uses the specialized fs mock
    mock_stop_event: MagicMock,
    mock_safe_file_mover: MagicMock,
) -> dict[str, Any]:
    """
    Provides a dictionary of mocked dependencies needed to instantiate
    RetryableFileSender for unit testing it in isolation.
    """
    logger.debug("Providing dependencies for RetryableFileSender unit test.")
    return {
        "remote_url": str(mock_config.remote_host_url),
        "request_timeout_seconds": float(mock_config.request_timeout),
        "verify_ssl": bool(mock_config.verify_ssl),
        "initial_backoff_seconds": float(mock_config.initial_backoff),
        "max_backoff_seconds": float(mock_config.max_backoff),
        "uploaded_destination_dir": Path(mock_config.uploaded_dir),
        "dead_letter_destination_dir": Path(mock_config.dead_letter_dir),
        "http_client": mock_http_client,
        "fs": mock_fs_for_sender_unit_tests,
        "stop_event": mock_stop_event,
        "safe_file_mover": mock_safe_file_mover,
    }


# --- 5. Generic Utility Path Fixtures ---
# These might become redundant if standard_test_dirs is used consistently.
# Kept for now if older tests rely on them, but consider migrating tests.


@pytest.fixture
def base_dir_legacy(tmp_path: Path) -> Path:
    """
    DEPRECATED (favor standard_test_dirs.base_dir):
    Provides a simple base temporary directory: tmp_path / "app" / "base".
    """
    logger.warning(
        "Fixture 'base_dir_legacy' is deprecated. Consider using 'standard_test_dirs'."
    )
    app_base = (
        tmp_path / "app_legacy_base"
    )  # Renamed to avoid conflict if used alongside standard
    app_base.mkdir(parents=True, exist_ok=True)
    return app_base


@pytest.fixture
def other_dirs_legacy(base_dir_legacy: Path) -> dict[str, Path]:
    """
    DEPRECATED (favor standard_test_dirs):
    Defines other directories relative to `base_dir_legacy`.
    Note: `mock_config` was updated to use `standard_test_dirs`, reducing need for this.
    """
    logger.warning(
        "Fixture 'other_dirs_legacy' is deprecated. Consider using 'standard_test_dirs'."
    )
    dirs = {
        "source_dir": base_dir_legacy / "source_legacy",
        "worker_dir": base_dir_legacy / "work_legacy",
        "uploaded_dir": base_dir_legacy / "done_legacy",  # Original had "done"
        "dead_letter_dir": base_dir_legacy / "dead_legacy",
        "csv_dir": base_dir_legacy / "reports_legacy",
    }

    return dirs


@pytest.fixture
def scan_dir_legacy(tmp_path: Path) -> Path:
    """
    DEPRECATED (tests needing a scan dir can use standard_test_dirs.source_dir or a sub-path):
    Empty temporary directory, originally for gather_file_data tests.
    """
    logger.warning("Fixture 'scan_dir_legacy' is deprecated.")
    d = tmp_path / "scan_dir_legacy"
    d.mkdir(parents=True, exist_ok=True)  # Ensure it's created
    return d


@pytest.fixture
def test_file_path_generic(tmp_path: Path) -> Path:  # Renamed from test_file_path
    """
    Provides a generic, empty sample file path within a temporary subdirectory.
    Useful for tests needing *a* file path without specific content initially.
    """
    # Using a clearer subdirectory structure for generic test files
    d = tmp_path / "generic_test_files"
    d.mkdir(parents=True, exist_ok=True)
    file = d / "sample_test_file.txt"
    # By default, the file is not created. Tests can create it if needed.
    # If tests usually expect it to exist, uncomment:
    # file.touch(exist_ok=True)
    return file
