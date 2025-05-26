import logging
import threading
from pathlib import Path
from queue import Queue

from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from datamover.file_functions.file_exceptions import ScanDirectoryError
from datamover.file_functions.fs_mock import FS
from datamover.file_functions.gather_entry_data import GatheredEntryData
from datamover.protocols import FileScanner
from datamover.queues.queue_functions import safe_put, QueuePutError

from datamover.tailer.data_class import TailerQueueEvent, InitialFoundEvent
from datamover.tailer.handler import MappingEventHandler
from datamover.tailer.tail_consumer_thread import TailConsumerThread
from datamover.tailer.tail_processor import TailProcessor

logger = logging.getLogger(__name__)

# --- Constants ---
INITIAL_SCAN_QUEUE_NAME = "InitialScanQueue"


def create_csv_tailer_thread(
    *,
    csv_directory_to_watch: Path,
    csv_file_extension_no_dot: str,
    event_queue: Queue[TailerQueueEvent],
    move_queue: Queue[Path],
    stop_event: threading.Event,
    fs: FS,
    file_scanner: FileScanner,
    poll_interval: float,
) -> tuple[BaseObserver, TailConsumerThread]:
    """
    Sets up CSV-tailing components using injected FS and FileScanner.

    Performs an initial scan for existing CSV files in the specified directory,
    enqueues InitialFoundEvent objects for them, configures a filesystem observer
    to watch for new/modified CSV files, and initializes the TailConsumerThread
    to process these events.

    Args:
        csv_directory_to_watch: The validated Path to the directory to monitor for CSV files.
        csv_file_extension_no_dot: The file extension (without a leading dot, e.g., "csv")
                                   to identify relevant files.
        event_queue: The queue for communication (accepts TailerQueueEvent objects)
                     between the file system event handler and the consumer thread.
        move_queue: The queue for file paths that need to be moved after processing.
        stop_event: Threading event to signal termination to the observer and consumer.
        fs: The filesystem abstraction instance to use for all operations.
        file_scanner: A callable conforming to the FileScanner protocol, used for
                      the initial scan of the directory.
        poll_interval: The interval (in seconds) for the consumer thread to poll

    Returns:
        A tuple containing the configured (but not started) Observer
        and TailConsumerThread.

    Raises:
        ValueError: If MappingEventHandler or TailProcessor initialization fails.
        ScanDirectoryError: If the initial directory scan (via file_scanner) fails critically.
        QueuePutError: If enqueuing initial files to the event_queue fails.
        # Other OS/FS errors from underlying operations might also propagate.
    """
    logger.info(
        "Configuring CSV tailer for directory: '%s' (extension: '.%s') using provided FS and FileScanner.",
        csv_directory_to_watch,
        csv_file_extension_no_dot,
    )

    # 1. Initial Scan to detect existing CSV files using the injected file_scanner
    try:
        logger.debug(
            "Starting initial scan for CSV files in '%s'", csv_directory_to_watch
        )
        initial_files_data: list[GatheredEntryData] = file_scanner(
            directory=csv_directory_to_watch,
            fs=fs,
            extension_no_dot=csv_file_extension_no_dot,
        )
        logger.info(
            "Initial scan found %d files matching '.%s' in '%s'",
            len(initial_files_data),
            csv_file_extension_no_dot,
            csv_directory_to_watch,
        )
    except ScanDirectoryError:
        logger.error(
            "Critical error during initial scan of '%s'.",
            csv_directory_to_watch,
            exc_info=True,
        )
        raise

    # 2. Build initial file map and enqueue InitialFoundEvent objects
    file_map: set[str] = set()  # Stores absolute string paths of known files
    processed_initial_files_count = 0
    for entry_data in initial_files_data:
        try:
            resolved_path: Path = fs.resolve(entry_data.path)
            abs_path_str: str = str(resolved_path)
        except (FileNotFoundError, OSError) as e:
            logger.warning(
                "Could not resolve path '%s' from initial scan (may have been deleted); skipping. Error: %s",
                entry_data.path,
                e,
            )
            continue

        file_map.add(abs_path_str)
        initial_event_object = InitialFoundEvent(path=abs_path_str)

        try:
            safe_put(
                item=initial_event_object,
                output_queue=event_queue,
                queue_name=INITIAL_SCAN_QUEUE_NAME,
            )
            processed_initial_files_count += 1
        except QueuePutError as e:
            logger.critical(
                "Failed to enqueue initial file event %s for queue '%s': %s. Aborting setup.",
                initial_event_object,
                INITIAL_SCAN_QUEUE_NAME,
                e,
                exc_info=True,
            )
            raise

    logger.info(
        "Finished enqueuing %d initial file events from '%s'.",
        processed_initial_files_count,
        csv_directory_to_watch,
    )

    # 3. Initialize Handler
    try:
        handler = MappingEventHandler(
            file_map=file_map,
            event_queue=event_queue,
            watched_directory=csv_directory_to_watch,
            fs=fs,
            file_extension=csv_file_extension_no_dot,
        )
    except ValueError as e:  # Handler might raise ValueError for bad args
        logger.error(
            "MappingEventHandler setup failed for '%s': %s",
            csv_directory_to_watch,
            e,
            exc_info=True,
        )
        raise

    # 4. Initialize Observer and schedule Handler
    observer: BaseObserver = Observer()
    observer.schedule(handler, str(csv_directory_to_watch), recursive=False)
    logger.info(
        "Watchdog observer scheduled for directory: '%s'", csv_directory_to_watch
    )

    # 5. Initialize Processor
    try:
        logger.debug("Initializing TailProcessor...")
        processor = TailProcessor(
            fs=fs,
            move_queue=move_queue,
            move_queue_name=f"MoveQueueFrom-{csv_directory_to_watch.name}",
        )
        logger.debug("TailProcessor initialized.")
    except Exception as e:  # Catch any init error from TailProcessor
        logger.error("TailProcessor initialization failed: %s", e, exc_info=True)
        raise ValueError("TailProcessor initialization failed") from e

    # 6. Initialize Consumer Thread
    logger.debug("Initializing TailConsumerThread...")
    tail_thread = TailConsumerThread(
        event_queue=event_queue,
        stop_event=stop_event,
        processor=processor,
        name=f"TailConsumer-{csv_directory_to_watch.name}",
        poll_interval=poll_interval,
    )
    logger.info(
        "TailConsumerThread '%s' initialized to process events for '%s'.",
        tail_thread.name,
        csv_directory_to_watch,
    )

    return observer, tail_thread
