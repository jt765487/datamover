import logging
import threading
from pathlib import Path
from typing import Union, Optional

import requests.exceptions

from datamover.file_functions.fs_mock import FS
from datamover.protocols import SafeFileMover, HttpResponse, HttpClient

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

        Args:
            file_path: The path to the file to send.

        Returns:
            True if the file sending process concluded decisively (moved to UPLOADED
                 or DEAD_LETTER, or source vanished).
            False if a CRITICAL error occurred (e.g., couldn't move to final
                  destination) or if stop_event was set mid-process.
        """
        file_name: str = file_path.name
        attempt: int = 1
        backoff: float = self._initial_backoff

        logger.debug("Attempting to process file for upload: '%s'", file_path)

        while not self._stop_event.is_set():
            # --- 1. Check source existence ---
            try:
                if not self._fs.exists(file_path):
                    logger.warning(
                        "Source file '%s' vanished before send attempt %d.",
                        file_path,
                        attempt,
                    )
                    return True  # Concluded decisively
            except OSError as e_exists:
                logger.error(
                    "OS Error checking source file '%s' existence before send attempt %d: %s. Aborting processing.",
                    file_path,
                    attempt,
                    e_exists,
                )
                return False  # Critical failure state

            # --- 2. Try Sending and Handle Response ---
            try:
                logger.debug(
                    "Upload attempt %d for '%s' to %s",
                    attempt,
                    file_name,
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

                # --- 3. Handle HTTP Response Codes ---
                status_code = response.status_code

                # --- 3a. Handle Success (2xx) ---
                if 200 <= status_code < 300:
                    logger.info(
                        "Upload SUCCESS for '%s' (Status: %d). Moving to UPLOADED dir.",
                        file_name,
                        status_code,
                    )
                    final_uploaded_path: Optional[Path] = self._safe_file_mover(
                        source_path_raw=file_path,
                        destination_dir=self._uploaded_dir,
                        fs=self._fs,
                        expected_source_dir=None,
                    )

                    if final_uploaded_path is None:
                        logger.critical(
                            "CRITICAL: Upload succeeded for '%s' but FAILED TO MOVE TO UPLOADED DIR '%s'. Requires manual intervention.",
                            file_path,
                            self._uploaded_dir,
                        )
                        return False
                    else:
                        logger.info(
                            "Successfully moved '%s' to UPLOADED dir: %s",
                            file_name,
                            final_uploaded_path,
                        )
                        return True

                # --- 3b. Handle Retryable Server Error (5xx) ---
                elif 500 <= status_code < 600:
                    logger.warning(
                        "Server error during upload attempt %d for '%s' (Status: %d). Retrying in %.1f sec...",
                        attempt,
                        file_name,
                        status_code,
                        backoff,
                    )
                    # Proceed to retry logic (handled by loop and wait below)

                # --- 3c. Handle Terminal HTTP Failure (non-2xx, non-5xx -> e.g., 4xx) ---
                else:
                    reason = f"Upload FAILED - terminal HTTP status ({status_code})"
                    return self._handle_terminal_failure(
                        file_path=file_path,
                        failure_reason=reason,
                        response_details=response.text,
                    )

            # --- 4. Handle Network Errors (Retryable) ---
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as net_err:
                logger.warning(
                    "Network error during upload attempt %d for '%s': %s. Retrying in %.1f sec...",
                    attempt,
                    file_name,
                    net_err,
                    backoff,
                )
                # Proceed to retry logic (handled by loop and wait below)

            # --- 5. Handle Other Request Errors (Non-Retryable HTTP Client Errors) ---
            except requests.exceptions.RequestException as req_err:
                return self._handle_terminal_failure(
                    file_path=file_path,
                    failure_reason=f"Non-retryable HTTP request exception ({type(req_err).__name__})",
                    exception_info=True,
                )

            # --- 6. Handle File I/O or Unexpected Errors during send attempt ---
            except FileNotFoundError:
                logger.warning(
                    "Source file '%s' vanished during send attempt %d (between exists check and open).",
                    file_path,
                    attempt,
                )
                return True
            except OSError as os_err:
                return self._handle_terminal_failure(
                    file_path=file_path,
                    failure_reason=f"OS error ({type(os_err).__name__}) during file open/read for upload",
                    exception_info=True,  # Ensure traceback for OS errors
                )
            except Exception as e:
                return self._handle_terminal_failure(
                    file_path=file_path,
                    failure_reason=f"Unexpected error ({type(e).__name__}) during send attempt",
                    exception_info=True,  # Ensure traceback for any other error
                )

            # --- 7. Retry Logic (Reached after 5xx or Network Error if not returned above) ---
            interrupted: bool = self._stop_event.wait(backoff)
            if interrupted:
                logger.info(
                    "Stop requested during retry backoff for '%s'. Aborting send.",
                    file_name,
                )
                return False

            attempt += 1
            backoff = min(backoff * 2, self._max_backoff)
            # continue will be implicitly called if no return statement was hit above in the try/except block

        # --- End of while loop (Stop event set between attempts or before first attempt) ---
        logger.info(
            "Stop signal detected; send process for '%s' aborted.",
            file_name,
        )
        return False
