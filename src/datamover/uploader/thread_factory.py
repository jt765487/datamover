import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from datamover.file_functions.directory_validation import (
    resolve_and_validate_directory,
)
from datamover.file_functions.fs_mock import FS
from datamover.file_functions.move_file_safely import (
    move_file_safely_impl,
)
from datamover.file_functions.scan_directory_and_filter import (
    scan_directory_and_filter,
)
from datamover.protocols import (
    HttpClient,
    SafeFileMover,
    FileScanner,
)

from datamover.uploader.send_file_with_retries import RetryableFileSender
from datamover.uploader.uploader_thread import UploaderThread

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploaderOperationalSettings:
    """Specific settings for the UploaderThread's operational behavior and directories."""

    worker_dir_path: Path
    uploaded_dir_path: Path
    dead_letter_dir_path: Path
    file_extension_to_scan: str
    poll_interval_seconds: float
    heartbeat_interval_seconds: float


@dataclass(frozen=True)
class SenderConnectionConfig:
    """Configuration for network connection, timeouts, and retry strategy for RetryableFileSender."""

    remote_host_url: str
    request_timeout_seconds: float
    verify_ssl: bool
    initial_backoff_seconds: float
    max_backoff_seconds: float


# --- Factory Function ---


def create_uploader_thread(
    *,
    uploader_op_settings: UploaderOperationalSettings,
    sender_conn_config: SenderConnectionConfig,
    stop_event: threading.Event,
    fs: FS,
    http_client: HttpClient,
    file_scanner_impl: FileScanner = scan_directory_and_filter,
    safe_file_mover_impl: SafeFileMover = move_file_safely_impl,
) -> UploaderThread:
    """
    Factory function to create and configure a single UploaderThread instance
    using grouped configuration settings.
    (Docstring would be updated to reflect UploaderOperationalSettings now includes heartbeat)
    """
    logger.info(
        "Creating UploaderThread for worker dir: '%s', sender URL: '%s'",
        uploader_op_settings.worker_dir_path,
        sender_conn_config.remote_host_url,
    )

    validated_worker_dir = resolve_and_validate_directory(
        raw_path=uploader_op_settings.worker_dir_path,
        fs=fs,
        dir_label="uploader source (worker) directory",
    )

    try:
        reliable_sender = RetryableFileSender(
            remote_url=sender_conn_config.remote_host_url,
            request_timeout_seconds=sender_conn_config.request_timeout_seconds,
            verify_ssl=sender_conn_config.verify_ssl,
            initial_backoff_seconds=sender_conn_config.initial_backoff_seconds,
            max_backoff_seconds=sender_conn_config.max_backoff_seconds,
            uploaded_destination_dir=uploader_op_settings.uploaded_dir_path,
            dead_letter_destination_dir=uploader_op_settings.dead_letter_dir_path,
            http_client=http_client,
            fs=fs,
            stop_event=stop_event,
            safe_file_mover=safe_file_mover_impl,
        )
    except Exception as e:  # pragma: no cover
        logger.error("Failed to initialize RetryableFileSender: %s", e, exc_info=True)
        raise

    thread_name = f"Uploader-{validated_worker_dir.name}"

    try:
        uploader_thread = UploaderThread(
            thread_name=thread_name,
            validated_work_dir=validated_worker_dir,
            file_extension_no_dot=uploader_op_settings.file_extension_to_scan,
            stop_event=stop_event,
            poll_interval=uploader_op_settings.poll_interval_seconds,
            heartbeat_interval=uploader_op_settings.heartbeat_interval_seconds,
            file_scanner=file_scanner_impl,
            file_sender=reliable_sender,
            fs=fs,
        )
    except Exception as e:  # pragma: no cover
        logger.error("Failed to initialize UploaderThread: %s", e, exc_info=True)
        raise

    logger.info("Successfully configured UploaderThread: %s", uploader_thread.name)
    return uploader_thread
