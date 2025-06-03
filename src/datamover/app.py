import logging
import queue
import threading
import time
from typing import Any

from datamover.file_functions.move_file_safely import move_file_safely_impl
from datamover.file_functions.scan_directory_and_filter import scan_directory_and_filter
from datamover.mover.thread_factory import create_file_move_thread
from datamover.purger.thread_factory import create_purger_thread
from datamover.scanner.thread_factory import create_scan_thread
from datamover.startup_code.context import AppContext
from datamover.tailer.thread_factory import create_csv_tailer_thread
from datamover.uploader.thread_factory import (
    create_uploader_thread,
    SenderConnectionConfig,
    UploaderOperationalSettings,
)

logger = logging.getLogger(__name__)


class AppRunFailureError(Exception):
    """Raised when the main app.run() encounters a critical unhandled error during operation."""

    pass


class AppSetupError(Exception):
    """Raised when app.run() fails during the initial setup/build/start phase."""

    pass


# Configuration constants
THREAD_JOIN_TIMEOUT = 5.0
HEALTH_CHECK_INTERVAL_SECONDS = 5.0
MOVE_QUEUE_MAXSIZE = 1000
TAILER_EVENT_QUEUE_MAXSIZE = 1000


def _initialize_queues() -> dict[str, queue.Queue]:
    logger.debug("Initializing application queues...")
    move_queue: queue.Queue = queue.Queue(maxsize=MOVE_QUEUE_MAXSIZE)
    tailer_queue: queue.Queue = queue.Queue(maxsize=TAILER_EVENT_QUEUE_MAXSIZE)
    logger.info(
        "Application queues initialized (MoveQ: %d, TailerQ: %d).",
        MOVE_QUEUE_MAXSIZE,
        TAILER_EVENT_QUEUE_MAXSIZE,
    )
    return {"move_queue": move_queue, "tailer_queue": tailer_queue}


def _define_thread_factory_specs(
    context: AppContext, queues: dict[str, queue.Queue]
) -> list[dict[str, Any]]:
    cfg = context.config
    return [
        {
            "key": "directory_scanner",
            "factory": create_scan_thread,
            "args_builder": lambda: {
                "scan_directory_path": cfg.source_dir,
                "csv_directory_to_put_restart_in": cfg.csv_dir,
                "file_extension_to_scan": cfg.pcap_extension_no_dot,
                "scan_interval_seconds": cfg.scanner_check_seconds,
                "lost_timeout_seconds": cfg.lost_timeout_seconds,
                "stuck_active_file_timeout_seconds": cfg.stuck_active_file_timeout_seconds,
                "lost_file_queue": queues["move_queue"],
                "stop_event": context.shutdown_event,
                "fs": context.fs,
                "time_func": time.time,
                "monotonic_func": time.monotonic,
            },
        },
        {
            "key": "file_mover",
            "factory": create_file_move_thread,
            "args_builder": lambda: {
                "source_dir_path": cfg.source_dir,
                "worker_dir_path": cfg.worker_dir,
                "poll_interval_seconds": cfg.move_poll_interval_seconds,
                "source_queue": queues["move_queue"],
                "stop_event": context.shutdown_event,
                "fs": context.fs,
                "sleep_func": time.sleep,
            },
        },
        {
            "key": "csv_tailer_components",
            "factory": create_csv_tailer_thread,
            "args_builder": lambda: {
                "csv_directory_to_watch": cfg.csv_dir,
                "csv_file_extension_no_dot": cfg.csv_extension_no_dot,
                "event_queue": queues["tailer_queue"],
                "move_queue": queues["move_queue"],
                "stop_event": context.shutdown_event,
                "fs": context.fs,
                "file_scanner": context.file_scanner,
                "poll_interval": cfg.event_queue_poll_timeout_seconds,
            },
        },
        {
            "key": "uploader",
            "factory": create_uploader_thread,
            "args_builder": lambda: {
                "uploader_op_settings": UploaderOperationalSettings(
                    worker_dir_path=cfg.worker_dir,
                    uploaded_dir_path=cfg.uploaded_dir,
                    dead_letter_dir_path=cfg.dead_letter_dir,
                    file_extension_to_scan=cfg.pcap_extension_no_dot,
                    poll_interval_seconds=cfg.uploader_poll_interval_seconds,
                    heartbeat_interval_seconds=cfg.heartbeat_target_interval_s,
                ),
                "sender_conn_config": SenderConnectionConfig(
                    remote_host_url=cfg.remote_host_url,
                    request_timeout_seconds=cfg.request_timeout,
                    verify_ssl=cfg.verify_ssl,
                    initial_backoff_seconds=cfg.initial_backoff,
                    max_backoff_seconds=cfg.max_backoff,
                ),
                "stop_event": context.shutdown_event,
                "fs": context.fs,
                "http_client": context.http_client,
                "file_scanner_impl": scan_directory_and_filter,
                "safe_file_mover_impl": move_file_safely_impl,
            },
        },
        {
            "key": "disk_purger",  # Changed key for clarity
            "factory": create_purger_thread,
            "args_builder": lambda: {
                "work_dir_path": cfg.worker_dir,
                "uploaded_dir_path": cfg.uploaded_dir,
                "fs": context.fs,
                # "total_disk_capacity_bytes": cfg.purger_total_disk_capacity_bytes,
                # "target_disk_usage_percent": cfg.purger_target_disk_usage_percent,
                # "check_interval_seconds": cfg.purger_check_interval_seconds,
                "total_disk_capacity_bytes": 1000,
                "target_disk_usage_percent": 0.8,
                "check_interval_seconds": 60.0,
                "stop_event": context.shutdown_event,
            },
        },
    ]


def _build_components(specs: list[dict[str, Any]]) -> tuple[dict[str, Any], list[Any]]:
    components: dict[str, Any] = {}
    to_join: list[Any] = []

    for spec in specs:
        component_key_being_built = spec["key"]
        logger.info("Building component %s...", component_key_being_built)
        instance_or_tuple = spec["factory"](**spec["args_builder"]())

        if component_key_being_built == "csv_tailer_components":
            observer, consumer = instance_or_tuple  # type: ignore[misc]
            components["observer"] = observer
            components["csv_tail_consumer"] = consumer
            to_join.extend([observer, consumer])
            if hasattr(observer, "daemon"):
                observer.daemon = True
            if hasattr(consumer, "daemon"):
                consumer.daemon = True
        else:
            instance = instance_or_tuple
            components[component_key_being_built] = instance
            to_join.append(instance)
            if hasattr(instance, "daemon"):
                instance.daemon = True
        logger.info("Built component %s.", component_key_being_built)
    return components, to_join


def _start_components(
    components: dict[str, Any],
    shutdown_event: threading.Event,
) -> None:
    started: list[Any] = []
    current_key: str = "<none_yet_started>"
    try:
        for key, obj in components.items():
            current_key = key
            name = getattr(obj, "name", key)
            logger.info("Starting %s (name: '%s')...", key, name)
            obj.start()
            started.append(obj)
            logger.info("%s (name: '%s') started.", key, name)

    except Exception as e:  # Catch errors during the start phase
        logger.critical(
            "Failed to start component %s: %s", current_key, e, exc_info=True
        )
        if not shutdown_event.is_set():
            shutdown_event.set()

        logger.info(
            "Attempting to join components already started in this batch due to start failure..."
        )
        for t in reversed(started):
            t_name = getattr(t, "name", "UnknownComponentInCleanup")
            if hasattr(t, "is_alive") and t.is_alive():
                logger.debug("Joining partially-started component %s...", t_name)
                try:
                    t.join(timeout=THREAD_JOIN_TIMEOUT / 2)
                except Exception as join_e:  # pragma: no cover
                    logger.warning(
                        "Error joining component %s during start failure cleanup: %s",
                        t_name,
                        join_e,
                    )
        raise  # Re-raise to be caught by run() and classified as AppSetupError


def _stop_and_join_components(
    components: dict[str, Any],
    to_join: list[Any],
    shutdown_event: threading.Event,
) -> None:
    shutdown_event.set()

    observer = components.get("observer")
    if observer and observer.is_alive():
        logger.info("Stopping observer...")
        observer.stop()

    csv_consumer = components.get("csv_tail_consumer")
    if csv_consumer and csv_consumer.is_alive() and hasattr(csv_consumer, "stop"):
        logger.info("Stopping csv_tail_consumer...")
        csv_consumer.stop()

    logger.info("Joining all components...")
    for obj in to_join:
        name = getattr(obj, "name", obj)
        if hasattr(obj, "is_alive") and obj.is_alive():
            logger.info("Joining %s...", name)
            obj.join(timeout=THREAD_JOIN_TIMEOUT)
            if obj.is_alive():
                logger.warning("%s did not shut down cleanly.", name)


def run(context: AppContext) -> None:
    thread_components: dict[str, Any] = {}
    objects_to_join: list[Any] = []

    logger.info("Starting main application run loop...")
    try:
        # --- Setup Phase ---
        queues = _initialize_queues()
        specs = _define_thread_factory_specs(context, queues)
        thread_components, objects_to_join = _build_components(specs)
        _start_components(thread_components, context.shutdown_event)
        # --- End of Setup Phase ---

        logger.info(
            "All components started successfully; supervising: %s",
            list(thread_components.keys()),
        )

        # --- Operational Phase (Health-check loop) ---
        while not context.shutdown_event.is_set():
            for key, obj in thread_components.items():
                if hasattr(obj, "is_alive") and not obj.is_alive():
                    name = getattr(obj, "name", key)
                    logger.critical(
                        "Component %s (%s) died—triggering shutdown.", key, name
                    )
                    if not context.shutdown_event.is_set():
                        context.shutdown_event.set()
                    # Raise AppRunFailureError for operational failures (health check)
                    raise AppRunFailureError(
                        f"Health-check failure: Component '{key}' (name: '{name}') died."
                    )

            interrupted = context.shutdown_event.wait(
                timeout=HEALTH_CHECK_INTERVAL_SECONDS
            )
            if interrupted:
                logger.info(
                    "Shutdown event received externally. Breaking health check loop."
                )
                break
        # End of while loop

    except AppRunFailureError:  # If health check raised it
        logger.info(
            "AppRunFailureError (operational) caught in run(), ensuring shutdown_event is set and re-raising."
        )
        context.shutdown_event.set()
        raise  # Re-raise for main.py to handle with sys.exit(1)
    except Exception as e:  # Catches errors from setup phase (_initialize_queues, _build_components, _start_components)
        logger.critical("Setup phase encountered a fatal error: %s", e, exc_info=True)
        if not context.shutdown_event.is_set():
            context.shutdown_event.set()
        # Raise AppSetupError for setup failures
        raise AppSetupError(f"app.run failed during setup: {e}") from e

    finally:
        logger.info("Initiating shutdown sequence.")
        _stop_and_join_components(
            thread_components, objects_to_join, context.shutdown_event
        )
        logger.info("Application shutdown complete.")
