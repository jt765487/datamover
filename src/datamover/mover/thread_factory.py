import logging
import time
import threading
from pathlib import Path
from queue import Queue
from typing import Optional

from datamover.file_functions.directory_validation import (
    resolve_and_validate_directory,
)
from datamover.file_functions.fs_mock import FS
from datamover.file_functions.move_file_safely import move_file_safely_impl
from datamover.protocols import SafeFileMover, SleepCallable
from datamover.mover.mover_thread import FileMoveThread

logger = logging.getLogger(__name__)


def create_file_move_thread(
    *,
    source_dir_path: Path,
    worker_dir_path: Path,
    poll_interval_seconds: float,
    source_queue: Queue[Path],
    stop_event: threading.Event,
    fs: FS,
    file_mover_func: Optional[SafeFileMover] = None,
    sleep_func: Optional[SleepCallable] = None,
) -> FileMoveThread:
    """
    Construct a FileMoveThread with all dependencies resolved.

    - Resolves configured source and worker dirs using the provided fs.
    - Uses the provided source_queue (shared across threads) for work items.
    - Uses the provided stop_event to control thread shutdown.
    - Injects the file moving logic via file_mover_func (conforming to SafeFileMover).

    Args:
        source_dir_path: The path to the source directory.
        worker_dir_path: The path to the worker (destination) directory.
        poll_interval_seconds: How often the thread should poll the source_queue.
        source_queue: Shared Queue instance for file paths to move.
        stop_event: Shared threading.Event to signal thread shutdown.
        fs: Filesystem abstraction instance (must be provided).
        file_mover_func: A callable conforming to the SafeFileMover protocol
                         responsible for safely moving a single file. Defaults
                         to move_file_safely_impl.
        sleep_func: Function to sleep (conforming to SleepCallable).
                         Passed to FileMoveThread for internal use.

    Returns:
        A configured FileMoveThread instance (daemon, not yet started).
    """
    # Resolve and validate configured directories using the passed-in paths
    # the calling code will catch Any exceptions from here in app.run
    src_dir = resolve_and_validate_directory(
        raw_path=source_dir_path,
        fs=fs,
        dir_label="source for FileMover",
    )
    dst_dir = resolve_and_validate_directory(
        raw_path=worker_dir_path,
        fs=fs,
        dir_label="destination for FileMover (worker)",
    )

    # Thread name based on the destination directory
    thread_name = f"FileMover-{dst_dir.name}"

    # Create the dependencies if not provided
    final_file_mover_func = (
        move_file_safely_impl if file_mover_func is None else file_mover_func
    )
    final_sleep_func = time.sleep if sleep_func is None else sleep_func

    # Build the process_single callback, capturing resolved paths and using file_mover_func
    def process_single_item(path_to_move: Path) -> None:
        """
        Processes a single file path from the queue using the injected file_mover_func.
        This function is the core work delegate for FileMoveThread.
        It handles logging for the thread's processing attempt.
        """
        try:
            final_dest_path: Optional[Path] = final_file_mover_func(  # Use renamed var
                source_path_raw=path_to_move,
                expected_source_dir=src_dir,
                destination_dir=dst_dir,
                fs=fs,
            )

            if final_dest_path:
                logger.debug(
                    "%s: Successfully processed and moved '%s' to '%s'",
                    thread_name,
                    path_to_move.name,
                    final_dest_path,
                )
            else:
                # This case implies the mover function itself handled logging for the specific failure reason
                logger.warning(
                    "%s: Failed to process '%s'. See previous logs from the file mover for details.",
                    thread_name,
                    path_to_move,
                )
        except Exception as e:
            # This catches unexpected errors in the process_single_item or file_mover_func
            logger.exception(
                "%s: Unexpected critical error during file processing for '%s': %s",
                thread_name,
                path_to_move,
                e,
            )

    # Construct and return the thread
    thread = FileMoveThread(
        source_queue=source_queue,
        process_single=process_single_item,
        stop_event=stop_event,
        sleep_func=final_sleep_func,  # Use renamed var
        name=thread_name,
        poll_interval=poll_interval_seconds,  # Use the direct argument
    )
    return thread
