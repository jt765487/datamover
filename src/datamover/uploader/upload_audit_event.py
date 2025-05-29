import logging
from typing import Optional, Dict, Any

audit_logger = logging.getLogger("datamover.upload_audit")


def create_upload_audit_event(
    level: int,  # e.g., logging.INFO, logging.WARNING, logging.ERROR
    event_type: str,
    file_name: str,
    file_size_bytes: Optional[int],
    destination_url: str,
    attempt: int,
    duration_ms: Optional[float],
    status_code: Optional[int] = None,
    backoff_seconds: Optional[float] = None,
    failure_category: Optional[str] = None,
    failure_detail: Optional[str] = None,
    exception_type: Optional[str] = None,
    response_text_snippet: Optional[str] = None,
) -> None:
    """
    Helper to construct the 'extra' dict and log an upload audit event.
    """
    extra_data: Dict[str, Any] = {
        "event_type": event_type,
        "file_name": file_name,
        "file_size_bytes": file_size_bytes,
        "destination_url": destination_url,
        "attempt": attempt,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
    }
    if status_code is not None:
        extra_data["status_code"] = status_code
    if backoff_seconds is not None:
        # Apply cast for Mypy
        extra_data["backoff_seconds"] = int(backoff_seconds)
    if failure_category is not None:
        extra_data["failure_category"] = failure_category
    if failure_detail is not None:
        extra_data["failure_detail"] = str(failure_detail)[:256]  # Truncate
    if exception_type is not None:
        extra_data["exception_type"] = exception_type
    if response_text_snippet is not None:
        extra_data["response_text_snippet"] = str(response_text_snippet)[:100]

    message = f"Upload audit: {event_type} for '{file_name}'"
    if status_code is not None:
        message += f" (Status: {status_code})"
    if failure_category:
        message += f" (Category: {failure_category})"
    if exception_type:
        message += f" (Exception: {exception_type})"

    audit_logger.log(level, message, extra=extra_data)
