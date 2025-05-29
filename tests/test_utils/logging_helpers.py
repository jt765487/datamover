import logging
from typing import Optional

import pytest


def find_log_record(
    caplog: pytest.LogCaptureFixture,
    level: int,
    required_substrings: Optional[list[str]] = None,
    logger_name: Optional[str] = None,
) -> Optional[logging.LogRecord]:
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
        logger_name: An optional logger name to filter by.

    Returns:
        The matching logging.LogRecord, or None if no match is found.
    """
    if required_substrings is None:
        required_substrings = []

    for record in reversed(caplog.records):
        if record.levelno == level:
            if logger_name and record.name != logger_name:
                continue
            if not required_substrings or all(
                sub in record.message for sub in required_substrings
            ):
                return record
    return None
