import logging
import pytest


def find_log_record(
    caplog: pytest.LogCaptureFixture,
    level: int,
    required_substrings: list[str] | None = None,
) -> logging.LogRecord | None:
    """
    Finds the first log record matching the specified level and containing
    all required substrings in its message.

    Searches in reverse (latest logs first).

    Args:
        caplog: The pytest LogCaptureFixture.
        level: The logging level to filter by (e.g., logging.INFO).
        required_substrings: An optional list of strings that must all be
                             present in the log record's message. If None or
                             empty, only level matching is performed.

    Returns:
        The matching logging.LogRecord, or None if no match is found.
    """
    if required_substrings is None:
        required_substrings = []

    for record in reversed(caplog.records):
        if record.levelno == level:
            # If no substrings are required, or if all required substrings are found
            if not required_substrings or all(
                sub in record.message for sub in required_substrings
            ):
                return record
    return None
