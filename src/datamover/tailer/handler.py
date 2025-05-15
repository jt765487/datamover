import logging
from os import fsdecode
from pathlib import Path
from queue import Queue
from typing import Optional

from watchdog.events import (
    FileCreatedEvent,
    DirCreatedEvent,
    FileModifiedEvent,
    DirModifiedEvent,
    FileDeletedEvent,
    DirDeletedEvent,
    FileMovedEvent,
    DirMovedEvent,
    FileSystemEventHandler,
)

from datamover.file_functions.fs_mock import FS
from datamover.queues.queue_functions import safe_put, QueuePutError

from datamover.tailer.data_class import (
    TailerQueueEvent,
    CreatedEvent,
    ModifiedEvent,
    DeletedEvent,
    MovedEvent,
)

logger = logging.getLogger(__name__)


class MappingEventHandler(FileSystemEventHandler):
    """
    Custom Watchdog FileSystemEventHandler monitoring a single directory non-recursively.

    Assumes watched_directory is pre-validated (absolute, resolved, exists, is a directory).
    Filters events for relevant files, maintains a map of known files, creates specific
    event dataclasses, and enqueues them.
    """

    QUEUE_NAME = "MappingEventHandlerQueue"

    def __init__(
        self,
        file_map: set[str],
        event_queue: Queue[TailerQueueEvent],
        watched_directory: Path,  # Assumed pre-validated by caller
        fs: FS,
        file_extension: str,
        queue_timeout: Optional[float] = None,
    ) -> None:
        super().__init__()
        self.file_map: set[str] = file_map
        self.event_queue: Queue[TailerQueueEvent] = event_queue
        self.fs: FS = fs
        self.queue_timeout: Optional[float] = queue_timeout

        # Watched directory is now assumed to be resolved and validated by the caller
        self.watched_directory: Path = watched_directory

        # Normalize file extension
        raw_extension = (
            file_extension if file_extension.startswith(".") else "." + file_extension
        )
        self.file_extension: str = raw_extension.lower()

        logger.info(
            "MappingEventHandler initialized for pre-validated directory '%s' and extension '%s'",
            self.watched_directory,
            self.file_extension,
        )

    def _safe_enqueue(self, event_object: TailerQueueEvent) -> None:
        try:
            safe_put(
                item=event_object,
                output_queue=self.event_queue,
                queue_name=self.QUEUE_NAME,
                timeout=self.queue_timeout,
            )
            logger.debug("Enqueued event: %s", event_object)
        except QueuePutError:
            logger.error(
                "Failed to enqueue event from MappingEventHandler. Event object: %s. Queue: %s",
                event_object,
                self.QUEUE_NAME,
            )

    def _is_path_within_monitored_directory(self, path_str: str) -> bool:
        try:
            # Resolve the incoming path_str using fs to ensure it's canonical
            # before comparing with self.watched_directory (which is already canonical)
            path_to_check = self.fs.resolve(Path(path_str))
            relative_path = self.fs.relative_to(path_to_check, self.watched_directory)
            return len(relative_path.parts) == 1 and str(relative_path) != "."
        except ValueError:
            return False
        except (FileNotFoundError, OSError) as e:
            logger.debug(
                "Error checking if path '%s' is within '%s': %s. Assuming not within.",
                path_str,
                self.watched_directory,
                e,
            )
            return False
        except Exception:
            logger.exception(
                "Unexpected error in _is_path_within_monitored_directory for path '%s' relative to '%s'. Assuming not within.",
                path_str,
                self.watched_directory,
            )
            return False

    def _should_process_file(self, path_str: str) -> bool:
        if not self._is_path_within_monitored_directory(path_str):
            logger.debug(
                "Ignoring event for path '%s': not directly within watched directory '%s'.",
                path_str,
                self.watched_directory,
            )
            return False
        if not path_str.lower().endswith(self.file_extension):
            logger.debug(
                "Ignoring event for path '%s': does not match extension '%s'.",
                path_str,
                self.file_extension,
            )
            return False
        return True

    def on_created(self, event: FileCreatedEvent | DirCreatedEvent) -> None:
        super().on_created(event)
        if event.is_directory:
            logger.debug("Ignoring directory creation: %s", event.src_path)
            return
        src_path_str: str = fsdecode(event.src_path)  # always gives you a Python str
        if not self._should_process_file(src_path_str):
            return
        logger.info("Detected relevant file creation: %s", src_path_str)
        self.file_map.add(src_path_str)
        event_object = CreatedEvent(path=src_path_str)
        self._safe_enqueue(event_object)

    def on_modified(self, event: FileModifiedEvent | DirModifiedEvent) -> None:
        super().on_modified(event)
        if event.is_directory:
            logger.debug("Ignoring directory modification: %s", event.src_path)
            return
        src_path_str: str = fsdecode(event.src_path)
        if not self._should_process_file(src_path_str):
            return
        if src_path_str not in self.file_map:
            logger.warning(
                "Modified file '%s' was not previously tracked or lost sync. Treating as creation.",
                src_path_str,
            )
            self.file_map.add(src_path_str)
            create_event_object = CreatedEvent(path=src_path_str)
            self._safe_enqueue(create_event_object)
        else:
            logger.info("Detected relevant file modification: %s", src_path_str)
            modified_event_object = ModifiedEvent(path=src_path_str)
            self._safe_enqueue(modified_event_object)

    def on_deleted(self, event: FileDeletedEvent | DirDeletedEvent) -> None:
        super().on_deleted(event)
        if event.is_directory:
            logger.debug("Ignoring directory deletion: %s", event.src_path)
            return
        src_path_str: str = fsdecode(event.src_path)
        if not self._is_path_within_monitored_directory(src_path_str):
            logger.debug(
                "Ignoring deletion for path '%s': not directly within watched directory '%s'.",
                src_path_str,
                self.watched_directory,
            )
            return
        if src_path_str not in self.file_map:
            logger.debug(
                "Ignoring deletion for untracked or irrelevant file: %s", src_path_str
            )
            return
        logger.info("Detected relevant file deletion: %s", src_path_str)
        self.file_map.discard(src_path_str)
        event_object = DeletedEvent(path=src_path_str)
        self._safe_enqueue(event_object)

    def on_moved(self, event: FileMovedEvent | DirMovedEvent) -> None:
        super().on_moved(event)
        if event.is_directory:
            logger.debug(
                "Ignoring directory move: %s -> %s", event.src_path, event.dest_path
            )
            return
        src_path_str: str = fsdecode(event.src_path)
        dst_path_str: str = fsdecode(event.dest_path)
        dst_is_within_watched_dir = self._is_path_within_monitored_directory(
            dst_path_str
        )
        src_was_tracked = src_path_str in self.file_map
        dst_is_relevant_target = (
            dst_is_within_watched_dir
            and dst_path_str.lower().endswith(self.file_extension)
        )
        if not src_was_tracked and not dst_is_relevant_target:
            logger.debug(
                "Ignoring move event: Neither source ('%s', tracked: %s) nor "
                "destination ('%s', relevant_target: %s) is relevant.",
                src_path_str,
                src_was_tracked,
                dst_path_str,
                dst_is_relevant_target,
            )
            return
        logger.info("Detected relevant file move: %s -> %s", src_path_str, dst_path_str)
        if src_was_tracked:
            self.file_map.discard(src_path_str)
        if dst_is_relevant_target:
            self.file_map.add(dst_path_str)
        event_object = MovedEvent(src_path=src_path_str, dest_path=dst_path_str)
        self._safe_enqueue(event_object)
