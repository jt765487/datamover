import threading
from unittest.mock import MagicMock, patch

import pytest

from datamover.protocols import FS, HttpClient, FileScanner
from datamover.startup_code.context import AppContext, build_context

# Path to the module where the items to be patched are looked up by build_context
CONTEXT_MODULE_PATH = "datamover.startup_code.context"


# --- Tests for AppContext Class ---


class TestAppContext:
    """Test suite for the AppContext class."""

    @pytest.fixture
    def mock_fs_obj(self) -> MagicMock:
        """Provides a mock FS object."""
        mock = MagicMock(spec=FS, name="mock_fs_instance")
        mock.__class__.__name__ = "MockedFS"  # For __str__ test
        return mock

    @pytest.fixture
    def mock_http_client_obj(self) -> MagicMock:
        """Provides a mock HttpClient object."""
        mock = MagicMock(spec=HttpClient, name="mock_http_client_instance")
        mock.__class__.__name__ = "MockedHttpClient"  # For __str__ test
        return mock

    @pytest.fixture
    def mock_file_scanner_obj(self) -> MagicMock:
        """Provides a mock FileScanner object."""
        mock = MagicMock(spec=FileScanner, name="mock_file_scanner_instance")
        mock.__name__ = "mocked_scan_function"  # For __str__ test
        return mock

    def test_app_context_initialization(
        self,
        mock_config: MagicMock,  # Uses mock_config from conftest.py
        mock_fs_obj: MagicMock,
        mock_http_client_obj: MagicMock,
        mock_file_scanner_obj: MagicMock,
    ):
        """
        Verify AppContext initializes correctly with config, fs, http_client,
        file_scanner, and sets up the shutdown_event.
        """
        # Act
        app_context = AppContext(
            config=mock_config,  # Use mock_config from conftest
            fs=mock_fs_obj,
            http_client=mock_http_client_obj,
            file_scanner=mock_file_scanner_obj,
        )

        # Assert
        assert app_context.config is mock_config
        assert app_context.fs is mock_fs_obj
        assert app_context.http_client is mock_http_client_obj
        assert app_context.file_scanner is mock_file_scanner_obj

        assert hasattr(app_context, "shutdown_event")
        assert isinstance(app_context.shutdown_event, threading.Event)
        assert not app_context.shutdown_event.is_set()

    @pytest.mark.parametrize("repr_function_to_test", [str, repr])
    def test_app_context_string_and_repr_representation(
        self,
        repr_function_to_test,
        mock_config: MagicMock,  # Uses mock_config from conftest.py
        mock_fs_obj: MagicMock,
        mock_http_client_obj: MagicMock,
        mock_file_scanner_obj: MagicMock,
    ):
        """
        Verify __str__ and __repr__ methods include new dependencies.
        """
        # Arrange

        app_context = AppContext(
            config=mock_config,
            fs=mock_fs_obj,
            http_client=mock_http_client_obj,
            file_scanner=mock_file_scanner_obj,
        )
        app_context.shutdown_event.clear()

        expected_representation = (
            "AppContext("
            "config_type=MagicMock, "  # ***** THIS IS THE FIX *****
            "fs=<MockedFS instance>, "
            "http_client=<MockedHttpClient instance>, "
            "file_scanner=mocked_scan_function, "
            "shutdown_event_set=False"
            ")"
        )

        # Act
        actual_representation = repr_function_to_test(app_context)

        # Assert
        assert actual_representation == expected_representation, (
            f"{repr_function_to_test.__name__}(AppContext) did not match expected format."
        )


# --- Tests for build_context Function ---


class TestBuildContext:
    """Test suite for the build_context factory function."""

    @patch(f"{CONTEXT_MODULE_PATH}.DefaultFSImplementation", autospec=True)
    @patch(f"{CONTEXT_MODULE_PATH}.DefaultHttpClientImplementation", autospec=True)
    @patch(f"{CONTEXT_MODULE_PATH}.default_file_scanner_implementation")
    def test_build_context_creates_and_configures_app_context_correctly(
        self,
        MockDefaultFileScannerFunc: MagicMock,
        MockDefaultHttpClientConst: MagicMock,
        MockDefaultFSConst: MagicMock,
        mock_config: MagicMock,  # Uses mock_config from conftest.py
    ):
        """
        Verify build_context instantiates default dependencies and creates AppContext.
        """
        # Arrange
        mock_fs_instance_created_by_sut = MagicMock(name="created_fs_instance_by_sut")
        MockDefaultFSConst.return_value = mock_fs_instance_created_by_sut

        mock_http_client_instance_created_by_sut = MagicMock(
            name="created_http_client_instance_by_sut"
        )
        MockDefaultHttpClientConst.return_value = (
            mock_http_client_instance_created_by_sut
        )

        # Act
        app_context = build_context(config=mock_config)  # Use mock_config from conftest

        # Assert
        assert isinstance(app_context, AppContext)

        MockDefaultFSConst.assert_called_once_with()
        MockDefaultHttpClientConst.assert_called_once_with()

        assert app_context.config is mock_config
        assert app_context.fs is mock_fs_instance_created_by_sut
        assert app_context.http_client is mock_http_client_instance_created_by_sut
        assert app_context.file_scanner is MockDefaultFileScannerFunc

        assert hasattr(app_context, "shutdown_event")
        assert isinstance(app_context.shutdown_event, threading.Event)
        assert not app_context.shutdown_event.is_set()


class TestBuildContextWithOverrides(TestBuildContext):  # Or a new class
    def test_build_context_uses_fs_override(
        self,
        mock_config: MagicMock,  # from conftest
    ):
        """Verify build_context uses the provided fs_override."""
        custom_fs_mock = MagicMock(spec=FS, name="custom_fs")

        app_context = build_context(config=mock_config, fs_override=custom_fs_mock)

        assert app_context.fs is custom_fs_mock
        # Ensure default HttpClient and FileScanner are still used if not overridden
        assert isinstance(
            app_context.http_client, HttpClient
        )  # Or check type if more specific
        assert (
            app_context.file_scanner is not None
        )  # default_file_scanner_implementation is a function

    def test_build_context_uses_http_client_override(
        self,
        mock_config: MagicMock,  # from conftest
    ):
        """Verify build_context uses the provided http_client_override."""
        custom_http_client_mock = MagicMock(spec=HttpClient, name="custom_http")

        app_context = build_context(
            config=mock_config, http_client_override=custom_http_client_mock
        )

        assert app_context.http_client is custom_http_client_mock
        assert isinstance(app_context.fs, FS)
        assert app_context.file_scanner is not None

    def test_build_context_uses_file_scanner_override(
        self,
        mock_config: MagicMock,  # from conftest
    ):
        """Verify build_context uses the provided file_scanner_override."""
        custom_file_scanner_mock = MagicMock(spec=FileScanner, name="custom_scanner")

        app_context = build_context(
            config=mock_config, file_scanner_override=custom_file_scanner_mock
        )

        assert app_context.file_scanner is custom_file_scanner_mock
        assert isinstance(app_context.fs, FS)
        assert isinstance(app_context.http_client, HttpClient)

    @patch(f"{CONTEXT_MODULE_PATH}.DefaultFSImplementation", autospec=True)
    @patch(f"{CONTEXT_MODULE_PATH}.DefaultHttpClientImplementation", autospec=True)
    @patch(f"{CONTEXT_MODULE_PATH}.default_file_scanner_implementation")
    def test_build_context_uses_all_overrides(
        self,
        MockDefaultFileScannerFunc: MagicMock,  # Patched, should not be used by AppContext
        MockDefaultHttpClientConst: MagicMock,  # Patched, should not be called
        MockDefaultFSConst: MagicMock,  # Patched, should not be called
        mock_config: MagicMock,
    ):
        """Verify build_context uses all provided overrides and defaults are not instantiated."""
        custom_fs = MagicMock(spec=FS, name="override_fs")
        custom_http = MagicMock(spec=HttpClient, name="override_http")
        custom_scanner = MagicMock(spec=FileScanner, name="override_scanner")

        app_context = build_context(
            config=mock_config,
            fs_override=custom_fs,
            http_client_override=custom_http,
            file_scanner_override=custom_scanner,
        )

        assert app_context.config is mock_config
        assert app_context.fs is custom_fs
        assert app_context.http_client is custom_http
        assert app_context.file_scanner is custom_scanner

        MockDefaultFSConst.assert_not_called()
        MockDefaultHttpClientConst.assert_not_called()
