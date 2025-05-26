import logging
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from typing import Optional, IO

from datamover.file_functions.fs_mock import FS
from datamover.queues.queue_functions import QueuePutError, safe_put

from datamover.tailer.data_class import (
    TailerQueueEvent,
    InitialFoundEvent,
    CreatedEvent,
    ModifiedEvent,
    DeletedEvent,
    MovedEvent,
)
from datamover.tailer.parse_csv_line import parse_log_line, ParsedLine
from datamover.tailer.utils import flush_buffer

logger = logging.getLogger(__name__)


class TailProcessor:
    """
    Processes file events to track content changes and parse new lines,
    mimicking 'tail -f' behavior based on specific rules.

    Uses an injected FS object for all filesystem interactions and directly
    uses specific parsing/buffering utility functions. Relies on `isinstance`
    checks on event dataclasses for dispatching.

    Core "tail -f" Logic Implemented:
    1.  Initial Tracking/Creation: On first sight (initial scan or create event),
        determine current size, track at EOF, do not read existing content.
    2.  Deletion Handling: Stop tracking deleted files, clear state.
    3.  Append Handling: On growth, seek to last known EOF, read only new data.
    4.  Truncation Handling: On shrink, reset tracked position to new (smaller)
        EOF, clear buffer, *do not read* existing content.
    5.  Move Handling: Treat as delete(source) + initial_track(destination).
    """

    # Type annotations for the class attributes
    fs: FS
    move_queue: Queue[Path]
    move_queue_name: str
    enqueuer: Callable[[Path], None]
    file_positions: dict[Path, int]
    file_buffers: dict[Path, bytes]

    def __init__(
        self,
        *,
        fs: FS,
        move_queue: Queue[Path],
        move_queue_name: str,
        enqueuer: Optional[Callable[[Path], None]] = None,
    ) -> None:
        """
        Initializes the TailProcessor.

        Args:
            fs: An injected filesystem abstraction object for all FS operations.
            move_queue: The queue onto which discovered file paths (from parsed
                        log lines) will be placed for further processing (e.g., moving).
            move_queue_name: A descriptive name for the move_queue, primarily
                             used for logging purposes.
            enqueuer: An optional callable that takes a Path and enqueues it.
                      If None, a default enqueuer using `safe_put` with the
                      provided `move_queue` will be used.
        """
        self.fs = fs
        self.move_queue = move_queue
        self.move_queue_name = move_queue_name

        # inject or fall back to default
        self.enqueuer = enqueuer or self._default_enqueue

        self.file_positions = {}
        self.file_buffers = {}

        logger.debug(
            "TailProcessor initialized - sending to queue [%s]", move_queue_name
        )

    def process_event(self, event: TailerQueueEvent) -> None:
        logger.debug("Processing event: %s", event)
        if isinstance(event, InitialFoundEvent):
            self._handle_track(Path(event.path), "Initial track")
        elif isinstance(event, CreatedEvent):
            self._handle_track(Path(event.path), "Created file")
        elif isinstance(event, ModifiedEvent):
            self._handle_modified(Path(event.path))
        elif isinstance(event, DeletedEvent):
            self._handle_deleted(Path(event.path))
        elif isinstance(event, MovedEvent):
            self._handle_moved(Path(event.src_path), Path(event.dest_path))
        else:
            logger.warning("Unhandled event type: %s", type(event))

    def _handle_track(self, path: Path, action: str) -> None:
        """On initial/fresh‐create: start tracking at EOF, no backfill."""
        try:
            if not self.fs.exists(path):
                logger.debug("%s: file not found %s, not tracking.", action, path)
                return
            size: int = self.fs.stat(path).st_size
        except OSError as e:
            logger.warning(
                "Could not stat file [%s] on %s: %s. Not tracking.", path, action, e
            )
            return

        self.file_positions[path] = size
        self.file_buffers[path] = b""
        logger.info("%s at EOF (%d bytes): %s", action, size, path)

    def _handle_modified(self, path: Path) -> None:  # Implicitly returns None
        """On modifications: read only new bytes, handle truncation, skip no-ops."""
        try:
            if not self.fs.exists(path):
                logger.warning(
                    "Modified event for non-existent file: %s. Treating as delete.",
                    path,
                )
                self._handle_deleted(path)  # Ensure state cleanup
                return
            current_size: int = self.fs.stat(path).st_size
        except OSError as e:
            logger.warning(
                "Could not stat file [%s] for modified: %s. Aborting.", path, e
            )
            return

        last_pos: Optional[int] = self.file_positions.get(path)
        if last_pos is None:
            logger.info("Late sync: untracked file modified, tracking now: %s", path)
            self._handle_track(path, "Late sync")
            return

        if current_size < last_pos:
            logger.warning(
                "File truncated (new %d < last %d), resetting to EOF: %s",
                current_size,
                last_pos,
                path,
            )
            self.file_positions[path] = current_size
            self.file_buffers[path] = b""
            return

        if current_size == last_pos:
            logger.debug("No change in size for %s (pos %d)", path, last_pos)
            return

        # appended data
        # Pass current_size to avoid re-stat in _read_appended_data and reduce race window
        data: bytes = self._read_appended_data(path, last_pos, current_size)
        if data:
            self._process_new_lines(path, data)
        # No explicit return needed if all paths lead to None or another return

    def _read_appended_data(
        self, path: Path, last_pos: int, current_size: int
    ) -> bytes:
        """Seek to last_pos and read only the new bytes up to current_size."""
        try:
            with self.fs.open(path, "rb") as f_obj:
                f: IO[bytes] = f_obj
                f.seek(last_pos)
                # current_size is from the stat in _handle_modified
                bytes_to_read: int = current_size - last_pos
                if bytes_to_read < 0:  # Should be caught by truncation logic, defensive
                    logger.warning(
                        "Bytes to read negative (%d) for %s. File may have shrunk. Reading 0 bytes.",
                        bytes_to_read,
                        path,
                    )
                    return b""
                new_data: bytes = f.read(bytes_to_read)
                self.file_positions[path] = f.tell()  # Update to actual position
                logger.debug(
                    "Read %d bytes from %s (requested %d)",
                    len(new_data),
                    path,
                    bytes_to_read,
                )
                return new_data
        except (OSError, ValueError) as e:  # ValueError for seek issues
            logger.warning(
                "Error reading data from %s at pos %d: %s", path, last_pos, e
            )
            return b""

    def _process_new_lines(self, path: Path, data: bytes) -> None:
        """
        Flush partial buffer into complete lines, hand them to parser,
        then enqueue each parsed target.
        """
        combined_buffer_data: bytes = self.file_buffers.get(path, b"") + data
        try:
            lines: list[str]
            remaining_binary_data: bytes
            # Assuming flush_buffer: (buffer: bytes) -> Tuple[List[str], bytes]
            lines, remaining_binary_data = flush_buffer(combined_buffer_data)

            self.file_buffers[path] = remaining_binary_data
            logger.debug(
                "Flushed buffer for %s: %d lines, %d bytes remaining in buffer",
                path,
                len(lines),
                len(remaining_binary_data),
            )
        except Exception as flush_err:
            logger.error(
                "Error flushing buffer for %s: %s", path, flush_err, exc_info=True
            )
            return

        for raw_line_str in lines:  # raw_line_str is str
            try:
                # parse_log_line returns ParsedLine
                parsed_item: ParsedLine = parse_log_line(raw_line_str)
                target_file_path: Path = Path(parsed_item.filepath)
                self.enqueuer(target_file_path)
            except QueuePutError as qe:
                logger.error(
                    "QueuePutError enqueuing target for line '%s' from '%s': %s",
                    raw_line_str[:100],
                    path,
                    qe,  # Log snippet of line and path
                )
            except (
                Exception
            ) as processing_err:  # Includes errors from parser e.g., LineParsing...
                logger.error(
                    "Error processing line '%s' from %s: %s",
                    raw_line_str[:100],
                    path,
                    processing_err,  # Log snippet of line and path
                    exc_info=True,
                )

    def _default_enqueue(self, target: Path) -> None:
        """
        The one place we call into safe_put. If you need back-off,
        metrics, special logging, do it here — all other code stays clean.
        """
        safe_put(
            item=target,
            output_queue=self.move_queue,
            queue_name=self.move_queue_name,
        )

    def _handle_deleted(self, path: Path) -> None:
        """Stop tracking any state for this file."""
        pos: Optional[int] = self.file_positions.pop(path, None)
        buf: Optional[bytes] = self.file_buffers.pop(path, None)
        if (
            pos is not None or buf is not None
        ):  # Log only if it was actually being tracked
            logger.info(
                "Stopped tracking deleted file %s (was at pos %s, buffer %d bytes)",
                path,
                pos if pos is not None else "N/A",
                len(buf) if buf is not None else 0,
            )
        else:
            logger.debug("Delete event for untracked or already removed file: %s", path)

    def _handle_moved(self, src: Path, dst: Path) -> None:
        """
        Treat a move as delete(src) + track(dst at EOF).
        """
        logger.info("File moved from %s to %s", src, dst)
        src_pos: Optional[int] = self.file_positions.pop(src, None)
        src_buf: Optional[bytes] = self.file_buffers.pop(src, None)
        if src_pos is not None or src_buf is not None:
            logger.debug(
                "Stopped tracking source of move %s (was at pos %s, buffer %d bytes)",
                src,
                src_pos if src_pos is not None else "N/A",
                len(src_buf) if src_buf is not None else 0,
            )

        # Track destination. _handle_track will handle if dst doesn't exist.
        self._handle_track(dst, "Track moved destination")
