from typing import Protocol, Optional, IO, Dict, List, Callable, runtime_checkable
from pathlib import Path

from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import GatheredEntryData


# --- Filesystem Related Protocols ---


class SafeFileMover(Protocol):
    """
    Protocol defining the interface for a callable that safely orchestrates
    the validation, destination path determination, and moving of a file
    using an injected FS object.
    """

    def __call__(
        self,
        *,
        source_path_raw: Path,
        destination_dir: Path,
        fs: FS,
        expected_source_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Orchestrates the safe move of a file.

        Args:
            source_path_raw: The source file path (may not be resolved).
            destination_dir: The target directory (should be resolved).
            fs: The filesystem abstraction instance to use for all operations.
            expected_source_dir: If provided (resolved Path), it triggers full
                                 validation logic within the implementation.
                                 If None, expects basic checks.

        Returns:
            The final destination Path object if the move was successful.
            None if any step (validation, destination conflict resolution,
            source vanishing, underlying move operation) failed.
        """
        ...


class FileScanner(Protocol):
    """Protocol for a callable that scans a directory for specific files and returns a list of GatheredEntryData."""

    def __call__(
        self, *, directory: Path, fs: FS, extension_no_dot: str
    ) -> List[GatheredEntryData]:
        """Scans the directory using fs for files with the given extension."""
        ...


# --- Timing/Concurrency Related Type Aliases/Protocols ---

SleepCallable = Callable[[float], None]
"""Type alias for a callable matching the signature of time.sleep."""

# --- HTTP Related Protocols ---


@runtime_checkable
class HttpResponse(Protocol):
    """Immutable view of an HTTP response."""

    @property
    def status_code(self) -> int: ...
    @property
    def text(self) -> str: ...

    # add other @property‐only attributes here as needed (headers, etc.)


@runtime_checkable
class HttpClient(Protocol):
    """Abstraction over any HTTP client."""

    def post(
        self,
        url: str,
        data: IO[bytes],
        headers: Dict[str, str],
        timeout: float,
        verify: bool,
    ) -> HttpResponse: ...
