from pathlib import Path
import pytest

from datamover.file_functions.file_exceptions import ScanDirectoryError


@pytest.mark.parametrize(
    "message, directory, original_exception",
    [
        pytest.param(
            "Failed to read directory contents",
            Path("/tmp/some/dir"),
            OSError("Permission denied"),
            id="os_error_case",
        ),
        pytest.param(
            "Specific failure point",
            Path("/data/input"),
            ValueError("Bad data"),
            id="value_error_case",
        ),
    ],
)
def test_scan_directory_error_instantiation_and_str(
    message: str, directory: Path, original_exception: Exception
):
    """
    ScanDirectoryError stores its attributes and its string
    representation is '{message} [Directory: {directory}]'.
    """
    err = ScanDirectoryError(
        message=message,
        directory=directory,
        original_exception=original_exception,
    )
    assert err.directory == directory
    assert err.original_exception is original_exception
    assert str(err) == f"{message} [Directory: {directory}]"


def test_scan_directory_error_raise_and_catch():
    """
    ScanDirectoryError can be raised and caught like a standard exception,
    preserving its attributes and message.
    """
    message = "Test raise"
    directory = Path("/dev/null")
    original_exception = TimeoutError("Timed out")

    err = ScanDirectoryError(
        message=message,
        directory=directory,
        original_exception=original_exception,
    )

    with pytest.raises(ScanDirectoryError) as excinfo:
        raise err

    caught = excinfo.value
    assert caught is err
    assert caught.directory == directory
    assert caught.original_exception is original_exception
    assert str(caught) == f"{message} [Directory: {directory}]"
