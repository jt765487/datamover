from pathlib import Path


class ScanDirectoryError(Exception):
    """Indicates a failure during the directory scanning process itself."""

    def __init__(self, message: str, directory: Path, original_exception: Exception):
        """
        Initializes the ScanDirectoryError.

        Args:
            message: A descriptive message explaining the error context.
            directory: The path to the directory where the scanning error occurred.
            original_exception: The original exception that triggered this error.
        """
        super().__init__(f"{message} [Directory: {directory}]")
        self.directory = directory
        self.original_exception = original_exception
