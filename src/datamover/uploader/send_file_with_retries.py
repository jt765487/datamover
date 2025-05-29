import logging
import threading
import time
from pathlib import Path
from typing import Union, Optional

import requests.exceptions

from datamover.file_functions.fs_mock import FS
from datamover.protocols import SafeFileMover, HttpResponse, HttpClient
from datamover.uploader.upload_audit_event import create_upload_audit_event

logger = logging.getLogger(__name__)


class RetryableFileSender:
    """
    Handles sending files via HTTP POST with retries (including for 5xx errors)
    and moves them to configured final destinations (uploaded or dead_letter)
    using injected dependencies.
    """

    def __init__(
        self,
        *,  # Force keyword-only arguments
        remote_url: str,
        request_timeout_seconds: float,
        verify_ssl: bool,
        initial_backoff_seconds: float,
        max_backoff_seconds: float,
        uploaded_destination_dir: Path,
        dead_letter_destination_dir: Path,
        http_client: HttpClient,
        fs: FS,
        stop_event: threading.Event,
        safe_file_mover: SafeFileMover,
    ):
        """
        Initializes the sender with shared dependencies and specific configuration values.

        Args:
            remote_url: The URL of the remote endpoint for uploads.
            request_timeout_seconds: Network request timeout for uploads.
            verify_ssl: Boolean indicating whether to verify SSL certificates.
            initial_backoff_seconds: Initial delay (seconds) for upload retries.
            max_backoff_seconds: Maximum delay (seconds) for upload retries.
            uploaded_destination_dir: Path to the directory for successfully uploaded files.
            dead_letter_destination_dir: Path to the directory for terminally failed files.
            http_client: An object adhering to the HttpClient protocol.
            fs: An object adhering to the FS protocol for filesystem access.
            stop_event: Threading event used for graceful shutdown.
            safe_file_mover: A callable adhering to the SafeFileMover protocol.
        """
        # Store injected dependencies
        self._http_client = http_client
        self._fs = fs
        self._stop_event = stop_event
        self._safe_file_mover = safe_file_mover

        # Store pre-extracted config values (now direct parameters)
        self._remote_url: str = remote_url
        self._request_timeout: float = request_timeout_seconds
        self._verify_ssl: bool = verify_ssl
        self._initial_backoff: float = initial_backoff_seconds
        self._max_backoff: float = max_backoff_seconds
        self._uploaded_dir: Path = uploaded_destination_dir
        self._dead_letter_dir: Path = dead_letter_destination_dir

        logger.info(
            "RetryableFileSender initialized for %s. Successful uploads to: '%s', Failed uploads to: '%s'",
            self._remote_url,
            self._uploaded_dir,
            self._dead_letter_dir,
        )

    def _handle_terminal_failure(
        self,
        *,
        file_path: Path,
        failure_reason: str,
        response_details: Optional[str] = None,
        exception_info: bool = False,
    ) -> bool:
        """
        Handles moving a file to the dead_letter_dir after a terminal failure.
        (Logic remains the same, uses self._dead_letter_dir which is correctly set)
        """
        log_parts = [f"{failure_reason} for file '%s'."]
        log_args: list[Union[str, Path]] = [file_path.name]
        if response_details:
            log_parts.append(" Response: %.100s...")
            log_args.append(response_details)
        log_parts.append(" Moving to DEAD LETTER.")
        log_msg_format = "".join(log_parts)

        logger.error(log_msg_format, *log_args, exc_info=exception_info)

        final_dest_path: Optional[Path] = self._safe_file_mover(
            source_path_raw=file_path,
            destination_dir=self._dead_letter_dir,  # Correct: uses updated attribute
            fs=self._fs,
            expected_source_dir=None,  # Current design choice
        )

        if final_dest_path is None:  # pragma: no cover
            logger.critical(
                "CRITICAL: File '%s' failed processing AND FAILED TO MOVE TO DEAD LETTER dir '%s'. Requires manual intervention.",
                file_path,
                self._dead_letter_dir,
            )
            return False
        else:
            logger.info(  # Changed from debug to info for visibility of this important terminal action
                "Successfully moved failed file '%s' to DEAD LETTER: %s",
                file_path.name,
                final_dest_path,
            )
            return True

    def send_file(self, file_path: Path) -> bool:
        """
        Attempts to send a single file via HTTP POST with retries for network
        errors and 5xx server errors. Moves the file to the configured _uploaded_dir
        on success or _dead_letter_dir on terminal failure (e.g., 4xx errors).
        Audits each significant step of the upload process.

        Args:
            file_path: The path to the file to send.

        Returns:
            True if the file sending process concluded decisively (moved to UPLOADED
                 or DEAD_LETTER, or source vanished).
            False if a CRITICAL error occurred (e.g., couldn't move to the final
                  destination) or if stop_event was set mid-process leading to abortion.
        """
        file_name: str = file_path.name
        attempt: int = 1
        backoff: float = self._initial_backoff

        logger.debug("Attempting to process file for upload: '%s'", file_path)

        # --- File Size (obtained once before loop if possible) ---
        file_size: Optional[int] = None
        try:
            # Check source existence before even trying to get size or loop
            if not self._fs.exists(file_path):
                logger.warning(
                    "Source file '%s' vanished before initial processing attempt.",
                    file_path,
                )
                # AUDIT: File vanished before any attempt
                create_upload_audit_event(
                    level=logging.WARNING,
                    event_type="upload_aborted_file_vanished_initially",
                    file_name=file_name,
                    file_size_bytes=None,  # Size unknown as it vanished
                    destination_url=self._remote_url,
                    attempt=0,  # No attempt made
                    duration_ms=None,
                    failure_category="File System State",
                    failure_detail=f"File '{file_path}' not found before first upload attempt.",
                )
                return True  # Concluded decisively

            file_size = self._fs.stat(file_path).st_size
        except OSError as e_stat_initial:
            logger.warning(
                "Could not get file size for '%s' due to OSError before first attempt: %s. Will proceed without file size if possible.",
                file_path,
                e_stat_initial,
            )
            # AUDIT: Failure to get file size (but will still attempt upload)
            create_upload_audit_event(
                level=logging.WARNING,
                event_type="upload_info_file_size_unavailable",
                file_name=file_name,
                file_size_bytes=None,
                destination_url=self._remote_url,
                attempt=0,  # Pre-attempt
                duration_ms=None,
                failure_category="File System Error",
                failure_detail=f"Failed to stat file '{file_path}': {e_stat_initial}",
                exception_type=type(e_stat_initial).__name__,
            )
            # file_size remains None, attempt will proceed

        while not self._stop_event.is_set():
            start_time_attempt: float = time.perf_counter()
            response_text_snippet_attempt: Optional[str] = None

            # --- 1a. Check source existence (again, per attempt, as it might vanish mid-retries) ---
            try:
                if not self._fs.exists(file_path):
                    logger.warning(
                        "Source file '%s' vanished before send attempt %d.",
                        file_path,
                        attempt,
                    )
                    # AUDIT: File vanished between retries
                    create_upload_audit_event(
                        level=logging.WARNING,
                        event_type="upload_aborted_file_vanished_midtries",
                        file_name=file_name,
                        file_size_bytes=file_size,  # Use last known size
                        destination_url=self._remote_url,
                        attempt=attempt,
                        duration_ms=(time.perf_counter() - start_time_attempt)
                        * 1000,  # Duration of this check
                        failure_category="File System State",
                        failure_detail=f"File '{file_path}' not found before attempt {attempt}.",
                    )
                    return True  # Concluded decisively
            except OSError as e_exists:
                logger.error(
                    "OS Error checking source file '%s' existence before send attempt %d: %s. Aborting processing.",
                    file_path,
                    attempt,
                    e_exists,
                )
                # AUDIT: OS error checking file existence
                create_upload_audit_event(
                    level=logging.ERROR,
                    event_type="upload_failure_fs_check_error",
                    file_name=file_name,
                    file_size_bytes=file_size,
                    destination_url=self._remote_url,
                    attempt=attempt,
                    duration_ms=(time.perf_counter() - start_time_attempt) * 1000,
                    failure_category="File System Error",
                    failure_detail=f"OS Error checking existence of '{file_path}': {e_exists}",
                    exception_type=type(e_exists).__name__,
                )
                # This is not a dead_letter scenario for the file itself yet, as we couldn't even check it.
                # But it's a critical state for this sender's operation on this file.
                return False  # Critical failure state for this file processing

            # Note: file_size is fetched once initially. If it couldn't be fetched, it's None.
            # Re-fetching size per attempt could be added if sizes can change and that's relevant.
            # For now, using the initially fetched (or None) file_size for all attempts.

            # --- 2. Try Sending and Handle Response ---
            try:
                logger.debug(  # Existing log
                    "Upload attempt %d for '%s' (size: %s bytes) to %s",
                    attempt,
                    file_name,
                    file_size if file_size is not None else "unknown",
                    self._remote_url,
                )
                headers: dict[str, str] = {
                    "x-filename": file_name,
                    "Content-Type": "application/octet-stream",
                }

                with self._fs.open(file_path, "rb") as f:
                    response: HttpResponse = self._http_client.post(
                        self._remote_url,
                        data=f,
                        headers=headers,
                        timeout=self._request_timeout,
                        verify=self._verify_ssl,
                    )

                duration_ms_attempt = (time.perf_counter() - start_time_attempt) * 1000
                http_status_code_attempt = response.status_code
                if response.text:
                    response_text_snippet_attempt = response.text[:100]

                # --- 3. Handle HTTP Response Codes ---

                # --- 3a. Handle Success (2xx) ---
                if 200 <= http_status_code_attempt < 300:
                    create_upload_audit_event(
                        level=logging.INFO,
                        event_type="upload_success",
                        file_name=file_name,
                        file_size_bytes=file_size,
                        destination_url=self._remote_url,
                        attempt=attempt,
                        duration_ms=duration_ms_attempt,
                        status_code=http_status_code_attempt,
                        response_text_snippet=response_text_snippet_attempt,
                    )

                    logger.info(  # Existing log
                        "Upload SUCCESS for '%s' (Status: %d, Attempt: %d, Duration: %.2fms). Moving to UPLOADED dir.",
                        file_name,
                        http_status_code_attempt,
                        attempt,
                        duration_ms_attempt,
                    )
                    final_uploaded_path: Optional[Path] = self._safe_file_mover(
                        source_path_raw=file_path,
                        destination_dir=self._uploaded_dir,
                        fs=self._fs,
                        expected_source_dir=None,
                    )

                    if final_uploaded_path is None:
                        logger.critical(  # Existing log
                            "CRITICAL: Upload succeeded for '%s' but FAILED TO MOVE TO UPLOADED DIR '%s'. Requires manual intervention.",
                            file_path,
                            self._uploaded_dir,
                        )

                        # AUDIT: Critical failure post-successful upload (move failed)
                        create_upload_audit_event(
                            level=logging.CRITICAL,
                            event_type="upload_failure_post_success_move",
                            file_name=file_name,
                            file_size_bytes=file_size,
                            destination_url=self._remote_url,  # URL of the successful upload
                            attempt=attempt,  # Successful attempt number
                            duration_ms=duration_ms_attempt,  # Duration of the successful upload
                            status_code=http_status_code_attempt,  # Status of the successful upload
                            failure_category="Post-Upload File Move Error",
                            failure_detail=f"Failed to move '{file_path}' to '{self._uploaded_dir}' after successful upload.",
                        )
                        return False
                    else:
                        logger.info(  # Existing log
                            "Successfully moved '%s' to UPLOADED dir: %s",
                            file_name,
                            final_uploaded_path,
                        )
                        return True  # SUCCESS

                # --- 3b. Handle Retryable Server Error (5xx) ---
                elif 500 <= http_status_code_attempt < 600:
                    current_failure_detail = (
                        f"HTTP Server Error, Status: {http_status_code_attempt}"
                    )
                    create_upload_audit_event(
                        level=logging.WARNING,
                        event_type="upload_retry_http_5xx",
                        file_name=file_name,
                        file_size_bytes=file_size,
                        destination_url=self._remote_url,
                        attempt=attempt,
                        duration_ms=duration_ms_attempt,
                        status_code=http_status_code_attempt,
                        backoff_seconds=backoff,
                        failure_category="HTTP Server Error",
                        failure_detail=current_failure_detail,
                        response_text_snippet=response_text_snippet_attempt,
                    )
                    logger.warning(  # Existing log
                        "Server error during upload attempt %d for '%s' (Status: %d, Duration: %.2fms). Retrying in %.1f sec...",
                        attempt,
                        file_name,
                        http_status_code_attempt,
                        duration_ms_attempt,
                        backoff,
                    )
                    # Proceed to retry logic (handled by loop and wait below)

                # --- 3c. Handle Terminal HTTP Failure (non-2xx, non-5xx -> e.g., 4xx) ---
                else:
                    current_failure_detail = (
                        f"Terminal HTTP Error, Status: {http_status_code_attempt}"
                    )
                    create_upload_audit_event(
                        level=logging.ERROR,
                        event_type="upload_failure_http_terminal",
                        file_name=file_name,
                        file_size_bytes=file_size,
                        destination_url=self._remote_url,
                        attempt=attempt,
                        duration_ms=duration_ms_attempt,
                        status_code=http_status_code_attempt,
                        failure_category="HTTP Terminal Error",
                        failure_detail=current_failure_detail,
                        response_text_snippet=response_text_snippet_attempt,
                    )
                    reason = f"Upload FAILED - terminal HTTP status ({http_status_code_attempt}) on attempt {attempt}"
                    # _handle_terminal_failure logs its own messages and moves to dead_letter
                    return self._handle_terminal_failure(
                        file_path=file_path,
                        failure_reason=reason,
                        response_details=response.text,  # Full response text for detailed logging
                    )

            # --- 4. Handle Network Errors (Retryable) ---
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as net_err:
                duration_ms_attempt = (
                    time.perf_counter() - start_time_attempt
                ) * 1000  # Capture duration up to error
                current_exception_type = type(net_err).__name__
                current_failure_detail = str(net_err)
                create_upload_audit_event(
                    level=logging.WARNING,
                    event_type="upload_retry_network_error",
                    file_name=file_name,
                    file_size_bytes=file_size,
                    destination_url=self._remote_url,
                    attempt=attempt,
                    duration_ms=duration_ms_attempt,
                    status_code=None,  # No HTTP status from these exceptions
                    backoff_seconds=backoff,
                    failure_category="Network Error",
                    failure_detail=current_failure_detail,
                    exception_type=current_exception_type,
                )
                logger.warning(  # Existing log
                    "Network error (%s) during upload attempt %d for '%s' (Duration: %.2fms): %s. Retrying in %.1f sec...",
                    current_exception_type,
                    attempt,
                    file_name,
                    duration_ms_attempt,
                    net_err,
                    backoff,
                )
                # Proceed to retry logic (handled by loop and wait below)

            # --- 5. Handle Other Request Errors (Non-Retryable HTTP Client Errors) ---
            except requests.exceptions.RequestException as req_err:
                duration_ms_attempt = (time.perf_counter() - start_time_attempt) * 1000
                current_exception_type = type(req_err).__name__
                current_failure_detail = str(req_err)
                create_upload_audit_event(
                    level=logging.ERROR,
                    event_type="upload_failure_client_request_exception",
                    file_name=file_name,
                    file_size_bytes=file_size,
                    destination_url=self._remote_url,
                    attempt=attempt,
                    duration_ms=duration_ms_attempt,
                    status_code=None,  # May or may not have status
                    failure_category="Client Request Error",
                    failure_detail=current_failure_detail,
                    exception_type=current_exception_type,
                )
                reason = f"Non-retryable HTTP request exception ({current_exception_type}) on attempt {attempt}"
                # _handle_terminal_failure logs its own messages and moves to dead_letter
                return self._handle_terminal_failure(
                    file_path=file_path,
                    failure_reason=reason,
                    # req_err might have a response attribute, but it's not guaranteed like HttpResponse
                    response_details=str(req_err),
                    exception_info=True,  # Include traceback for these unexpected request errors
                )

            # --- 6. Handle File I/O or Unexpected Errors during send attempt's try block ---
            except (
                FileNotFoundError
            ):  # Specifically during fs.open() or http_client.post() if it reads file
                duration_ms_attempt = (time.perf_counter() - start_time_attempt) * 1000
                current_exception_type = "FileNotFoundError"
                current_failure_detail = f"File '{file_path}' vanished during active send attempt {attempt} (open/read phase)."
                create_upload_audit_event(
                    level=logging.WARNING,  # Changed to WARNING as it's a mid-process vanish
                    event_type="upload_failure_file_vanished_during_send",
                    file_name=file_name,
                    file_size_bytes=file_size,  # Last known size
                    destination_url=self._remote_url,
                    attempt=attempt,
                    duration_ms=duration_ms_attempt,
                    failure_category="File System State",
                    failure_detail=current_failure_detail,
                    exception_type=current_exception_type,
                )
                logger.warning(  # Existing log (adapted)
                    "%s Duration: %.2fms",
                    current_failure_detail,
                    duration_ms_attempt,
                )
                return True  # Concluded decisively, file is gone

            except OSError as os_err:  # Other OS errors during fs.open() or read
                duration_ms_attempt = (time.perf_counter() - start_time_attempt) * 1000
                current_exception_type = type(os_err).__name__
                current_failure_detail = (
                    f"OS error during file open/read for upload: {os_err}"
                )
                create_upload_audit_event(
                    level=logging.ERROR,
                    event_type="upload_failure_os_error_send",
                    file_name=file_name,
                    file_size_bytes=file_size,
                    destination_url=self._remote_url,
                    attempt=attempt,
                    duration_ms=duration_ms_attempt,
                    failure_category="File System Error",
                    failure_detail=current_failure_detail,
                    exception_type=current_exception_type,
                )
                reason = f"OS error ({current_exception_type}) during file open/read for upload on attempt {attempt}"
                return self._handle_terminal_failure(
                    file_path=file_path,
                    failure_reason=reason,
                    response_details=str(os_err),
                    exception_info=True,
                )

            except (
                Exception
            ) as e:  # Catch-all for unexpected errors during the send attempt
                duration_ms_attempt = (time.perf_counter() - start_time_attempt) * 1000
                current_exception_type = type(e).__name__
                current_failure_detail = f"Unexpected error during send attempt: {e}"
                create_upload_audit_event(
                    level=logging.ERROR,
                    event_type="upload_failure_unexpected_send",
                    file_name=file_name,
                    file_size_bytes=file_size,
                    destination_url=self._remote_url,
                    attempt=attempt,
                    duration_ms=duration_ms_attempt,
                    failure_category="Unexpected Error",
                    failure_detail=current_failure_detail,
                    exception_type=current_exception_type,
                )
                reason = f"Unexpected error ({current_exception_type}) during send attempt {attempt}"
                return self._handle_terminal_failure(
                    file_path=file_path,
                    failure_reason=reason,
                    response_details=str(e),
                    exception_info=True,
                )

            # --- 7. Retry Logic (Reached after 5xx or Network Error if not returned above) ---
            # If we reach here, it means the attempt resulted in a retryable error.
            logger.debug(
                "Upload attempt %d for '%s' concluded with a retryable error. Preparing for backoff of %.1f sec.",
                attempt,
                file_name,
                backoff,
            )

            interrupted: bool = self._stop_event.wait(backoff)
            if interrupted:
                logger.info(  # Existing log
                    "Stop requested during retry backoff for '%s' (after attempt %d). Aborting send.",
                    file_name,
                    attempt,
                )
                # AUDIT: Upload process aborted due to stop signal during backoff
                create_upload_audit_event(
                    level=logging.INFO,
                    event_type="upload_aborted_shutdown_during_backoff",
                    file_name=file_name,
                    file_size_bytes=file_size,
                    destination_url=self._remote_url,
                    attempt=attempt,  # The attempt that just failed and led to this backoff
                    duration_ms=None,  # Duration here refers to the backoff itself, not an attempt
                    failure_category="Process Interruption",
                    failure_detail=f"Upload process for '{file_name}' aborted during backoff (after attempt {attempt}) due to stop signal.",
                )
                return False  # Abort due to stop signal

            attempt += 1
            backoff = min(backoff * 2, self._max_backoff)
            # continue to next iteration of the while loop for the next attempt

        # --- End of while loop (Executes if `not self._stop_event.is_set()` becomes false) ---
        logger.info(
            "Stop signal detected; send process for '%s' aborted before attempt %d could start/complete.",
            file_name,
            attempt,
        )

        return False  # Abort due to stop signal
