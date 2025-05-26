import threading
from typing import Optional

# Import concrete default implementations
from datamover.file_functions.fs_mock import FS as DefaultFSImplementation
from datamover.file_functions.scan_directory_and_filter import (
    scan_directory_and_filter as default_file_scanner_implementation,
)
from datamover.protocols import FS, HttpClient, FileScanner  # For type hinting
from datamover.startup_code.load_config import Config
from datamover.uploader.http_adapters import (
    RequestsHttpClientAdapter as DefaultHttpClientImplementation,
)


class AppContext:
    def __init__(
        self, config: Config, fs: FS, http_client: HttpClient, file_scanner: FileScanner
    ):
        self.shutdown_event = threading.Event()
        self.config: Config = config
        self.fs: FS = fs
        self.http_client: HttpClient = http_client
        self.file_scanner: FileScanner = file_scanner

    def __str__(self) -> str:
        fs_repr = f"<{self.fs.__class__.__name__} instance>"
        http_client_repr = f"<{self.http_client.__class__.__name__} instance>"
        file_scanner_repr = getattr(
            self.file_scanner, "__name__", str(self.file_scanner)
        )
        return (
            f"{self.__class__.__name__}("
            f"config_type={type(self.config).__name__}, "
            f"fs={fs_repr}, "
            f"http_client={http_client_repr}, "
            f"file_scanner={file_scanner_repr}, "
            f"shutdown_event_set={self.shutdown_event.is_set()}"
            f")"
        )

    __repr__ = __str__


def build_context(
    config: Config,
    fs_override: Optional[FS] = None,
    http_client_override: Optional[HttpClient] = None,
    file_scanner_override: Optional[FileScanner] = None,
) -> AppContext:
    """
    Factory function to create an AppContext instance.
    Allows overriding default dependencies for testing or alternative implementations.
    """
    # Use override if provided, otherwise instantiate default implementations
    fs_instance: FS = (
        fs_override if fs_override is not None else DefaultFSImplementation()
    )

    http_client_instance: HttpClient = (
        http_client_override
        if http_client_override is not None
        else DefaultHttpClientImplementation()
    )

    file_scanner_instance: FileScanner = (
        file_scanner_override
        if file_scanner_override is not None
        else default_file_scanner_implementation
    )

    return AppContext(
        config=config,
        fs=fs_instance,
        http_client=http_client_instance,
        file_scanner=file_scanner_instance,
    )
