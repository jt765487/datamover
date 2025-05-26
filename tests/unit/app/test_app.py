import logging
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import datamover.app as app_module
from datamover.app import AppRunFailureError, AppSetupError
from datamover.protocols import FS, HttpClient, FileScanner
from tests.test_utils.logging_helpers import find_log_record

# Import SUT dependencies for test_run_factory_arguments_passed_correctly
from datamover.uploader.thread_factory import (
    UploaderOperationalSettings,
    SenderConnectionConfig,
)
from datamover.file_functions.scan_directory_and_filter import scan_directory_and_filter
from datamover.file_functions.move_file_safely import move_file_safely_impl

logger = logging.getLogger(__name__)

SUT_THREAD_JOIN_TIMEOUT = app_module.THREAD_JOIN_TIMEOUT
SUT_HEALTH_CHECK_INTERVAL = app_module.HEALTH_CHECK_INTERVAL_SECONDS


def create_mock_thread_object(name="mock_thread_obj") -> MagicMock:
    thread_obj = MagicMock(spec=threading.Thread)
    thread_obj.name = name
    thread_obj._test_is_alive_flag = True

    def mock_is_alive() -> bool:
        return thread_obj._test_is_alive_flag

    def mock_join(timeout=None) -> None:
        thread_obj._test_is_alive_flag = False  # Simulate thread finishing upon join

    def mock_stop() -> None:
        pass

    thread_obj.is_alive = MagicMock(side_effect=mock_is_alive)
    thread_obj.join = MagicMock(side_effect=mock_join)
    thread_obj.stop = MagicMock(side_effect=mock_stop)
    thread_obj.start = MagicMock()
    return thread_obj


@pytest.fixture
def mock_app_context(mock_config) -> SimpleNamespace:
    ctx = SimpleNamespace(config=mock_config, shutdown_event=threading.Event())
    ctx.fs = MagicMock(spec=FS, name="context_mock_fs")
    ctx.http_client = MagicMock(spec=HttpClient, name="context_mock_http_client")
    ctx.file_scanner = MagicMock(spec=FileScanner, name="context_mock_file_scanner")
    return ctx


@pytest.fixture
def mock_queues(monkeypatch) -> dict[str, MagicMock]:
    mock_move_q = MagicMock(spec=queue.Queue, name="mock_move_queue")
    mock_tailer_q = MagicMock(spec=queue.Queue, name="mock_tailer_queue")
    queue_creation_order = [mock_move_q, mock_tailer_q]
    monkeypatch.setattr(
        app_module.queue, "Queue", MagicMock(side_effect=queue_creation_order)
    )
    return {"move_queue": mock_move_q, "tailer_queue": mock_tailer_q}


@pytest.fixture
def mock_all_thread_factories_and_components(monkeypatch) -> dict:
    mock_components = {
        "directory_scanner": create_mock_thread_object("scanner_mock_obj"),
        "file_mover": create_mock_thread_object("mover_mock_obj"),
        "observer": create_mock_thread_object("observer_mock_obj"),
        "csv_tail_consumer": create_mock_thread_object("csv_consumer_mock_obj"),
        "uploader": create_mock_thread_object("uploader_mock_obj"),
    }
    mock_factories = {
        "create_scan_thread": MagicMock(
            return_value=mock_components["directory_scanner"],
            name="patched_create_scan_thread",
        ),
        "create_file_move_thread": MagicMock(
            return_value=mock_components["file_mover"],
            name="patched_create_file_move_thread",
        ),
        "create_csv_tailer_thread": MagicMock(
            return_value=(
                mock_components["observer"],
                mock_components["csv_tail_consumer"],
            ),
            name="patched_create_csv_tailer_thread",
        ),
        "create_uploader_thread": MagicMock(
            return_value=mock_components["uploader"],
            name="patched_create_uploader_thread",
        ),
    }
    for name, mock_factory_func in mock_factories.items():
        monkeypatch.setattr(app_module, name, mock_factory_func)
    return {"factories": mock_factories, "components": mock_components}


def test_run_successful_initialization_start_and_shutdown(
    mock_app_context: SimpleNamespace,
    mock_all_thread_factories_and_components: dict,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    mock_app_context.shutdown_event.clear()

    for comp in mock_all_thread_factories_and_components["components"].values():
        comp._test_is_alive_flag = True
        comp.start.reset_mock()
        comp.join.reset_mock()
        comp.stop.reset_mock()

    run_app_thread = threading.Thread(target=app_module.run, args=(mock_app_context,))
    run_app_thread.start()
    time.sleep(min(SUT_HEALTH_CHECK_INTERVAL / 2, 0.5))
    assert run_app_thread.is_alive(), (
        "app.run() should be blocking in health check loop"
    )

    mock_app_context.shutdown_event.set()
    run_app_thread.join(
        timeout=SUT_THREAD_JOIN_TIMEOUT + SUT_HEALTH_CHECK_INTERVAL + 1.0
    )
    assert not run_app_thread.is_alive(), (
        "app.run() did not exit after shutdown_event was set"
    )

    mock_factories = mock_all_thread_factories_and_components["factories"]
    mock_components = mock_all_thread_factories_and_components["components"]

    for factory_mock in mock_factories.values():
        factory_mock.assert_called_once()
    for component_obj in mock_components.values():
        component_obj.start.assert_called_once()

    mock_components["observer"].stop.assert_called_once()
    if hasattr(mock_components["csv_tail_consumer"], "stop"):
        mock_components["csv_tail_consumer"].stop.assert_called_once()

    for component_obj in mock_components.values():
        component_obj.join.assert_called_once_with(timeout=SUT_THREAD_JOIN_TIMEOUT)

    assert find_log_record(
        caplog, logging.INFO, ["Starting main application run loop..."]
    )
    assert find_log_record(
        caplog, logging.INFO, ["All components started successfully; supervising:"]
    )
    assert find_log_record(
        caplog,
        logging.INFO,
        ["Shutdown event received externally. Breaking health check loop."],
    )
    assert find_log_record(caplog, logging.INFO, ["Application shutdown complete."])


def test_run_initialization_failure_in_build_phase_raises_appsetuperror(
    mock_app_context: SimpleNamespace,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    build_exception = ValueError("Scanner factory build deliberately failed")

    failing_scan_factory = MagicMock(
        side_effect=build_exception, name="failing_create_scan_thread_mock"
    )
    monkeypatch.setattr(app_module, "create_scan_thread", failing_scan_factory)
    mock_move_factory = MagicMock(name="move_factory_not_called")
    monkeypatch.setattr(app_module, "create_file_move_thread", mock_move_factory)

    with pytest.raises(AppSetupError) as excinfo:
        app_module.run(mock_app_context)

    assert excinfo.value.__cause__ is build_exception
    failing_scan_factory.assert_called_once()
    mock_move_factory.assert_not_called()

    log_record_setup_phase = find_log_record(
        caplog,
        logging.CRITICAL,
        ["Setup phase encountered a fatal error", str(build_exception)],
    )
    assert log_record_setup_phase is not None
    assert log_record_setup_phase.exc_info[1] is build_exception
    assert mock_app_context.shutdown_event.is_set()
    assert find_log_record(caplog, logging.INFO, ["Application shutdown complete."])


def test_run_thread_start_failure_raises_appsetuperror(
    mock_app_context: SimpleNamespace,
    monkeypatch,
    mock_all_thread_factories_and_components: dict,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)

    mock_components = mock_all_thread_factories_and_components["components"]

    for key, comp in mock_components.items():
        comp.start.reset_mock()
        comp.join.reset_mock()
        comp._test_is_alive_flag = True

    scanner_thread_ok = mock_components["directory_scanner"]
    mover_thread_fails_start = mock_components["file_mover"]

    start_failure_exception = RuntimeError("Mover start deliberate failure")
    mover_thread_fails_start.start.side_effect = start_failure_exception

    with pytest.raises(AppSetupError) as excinfo:
        app_module.run(mock_app_context)

    assert excinfo.value.__cause__ is start_failure_exception

    scanner_thread_ok.start.assert_called_once()
    mover_thread_fails_start.start.assert_called_once()
    mock_components["observer"].start.assert_not_called()  # And other subsequent ones

    log_record_start_fail_specific = find_log_record(
        caplog,
        logging.CRITICAL,
        ["Failed to start component file_mover", str(start_failure_exception)],
    )
    assert log_record_start_fail_specific is not None
    assert log_record_start_fail_specific.exc_info[1] is start_failure_exception

    log_record_setup_phase = find_log_record(
        caplog,
        logging.CRITICAL,
        ["Setup phase encountered a fatal error", str(start_failure_exception)],
    )
    assert log_record_setup_phase is not None
    assert log_record_setup_phase.exc_info[1] is start_failure_exception

    assert mock_app_context.shutdown_event.is_set()

    # scanner_thread_ok was started and then joined in _start_components's cleanup
    scanner_thread_ok.join.assert_called_once_with(timeout=SUT_THREAD_JOIN_TIMEOUT / 2)

    # These components were BUILT. Their start() either failed or was not reached.
    # They will be joined by the main finally block -> _stop_and_join_components
    mover_thread_fails_start.join.assert_called_once_with(
        timeout=SUT_THREAD_JOIN_TIMEOUT
    )
    mock_components["observer"].join.assert_called_once_with(
        timeout=SUT_THREAD_JOIN_TIMEOUT
    )
    mock_components["csv_tail_consumer"].join.assert_called_once_with(
        timeout=SUT_THREAD_JOIN_TIMEOUT
    )
    mock_components["uploader"].join.assert_called_once_with(
        timeout=SUT_THREAD_JOIN_TIMEOUT
    )

    assert find_log_record(caplog, logging.INFO, ["Application shutdown complete."])
    assert (
        find_log_record(caplog, logging.INFO, ["All components started successfully"])
        is None
    )


def test_health_check_detects_dead_thread_and_raises_apprunfailure(
    mock_app_context: SimpleNamespace,
    mock_all_thread_factories_and_components: dict,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    mock_app_context.shutdown_event.clear()

    mock_components = mock_all_thread_factories_and_components["components"]
    scanner_thread_mock = mock_components["directory_scanner"]
    assert scanner_thread_mock.name == "scanner_mock_obj"

    for comp in mock_components.values():
        comp._test_is_alive_flag = True
        comp.start.reset_mock()
        comp.join.reset_mock()
        comp.stop.reset_mock()

    original_wait = mock_app_context.shutdown_event.wait
    wait_call_count = 0

    def short_wait_then_kill(timeout):
        nonlocal wait_call_count
        wait_call_count += 1
        if wait_call_count > 1:
            scanner_thread_mock._test_is_alive_flag = False
        return original_wait(0.01 if timeout > 0 else 0)

    mock_app_context.shutdown_event.wait = MagicMock(side_effect=short_wait_then_kill)

    health_check_failure_message_regex = r"Health-check failure: Component 'directory_scanner' \(name: 'scanner_mock_obj'\) died\."

    with pytest.raises(AppRunFailureError, match=health_check_failure_message_regex):
        app_module.run(mock_app_context)

    assert mock_app_context.shutdown_event.is_set()

    assert find_log_record(
        caplog,
        logging.CRITICAL,
        ["Component directory_scanner (scanner_mock_obj) died—triggering shutdown"],
    ), "Missing critical log for dead component"

    assert find_log_record(
        caplog, logging.INFO, ["AppRunFailureError (operational) caught in run()"]
    )

    assert find_log_record(caplog, logging.INFO, ["Initiating shutdown sequence."])
    assert find_log_record(caplog, logging.INFO, ["Application shutdown complete."])

    for comp_key, comp_obj in mock_components.items():
        comp_obj.start.assert_called_once()
        if comp_key == "directory_scanner":  # This is the one that "died"
            comp_obj.join.assert_not_called()  # Because it's not is_alive() when _stop_and_join_components checks
        else:
            comp_obj.join.assert_called_once_with(timeout=SUT_THREAD_JOIN_TIMEOUT)


def test_run_factory_arguments_passed_correctly(
    mock_app_context: SimpleNamespace,
    mock_queues: dict[str, MagicMock],
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)

    inspectable_factories = {
        "create_scan_thread": MagicMock(name="inspectable_create_scan_thread_mock"),
        "create_file_move_thread": MagicMock(
            name="inspectable_create_file_move_thread_mock"
        ),
        "create_csv_tailer_thread": MagicMock(
            name="inspectable_create_csv_tailer_thread_mock"
        ),
        "create_uploader_thread": MagicMock(
            name="inspectable_create_uploader_thread_mock"
        ),
    }

    mock_threads_returned = {
        "scanner": create_mock_thread_object("scanner_thread_for_args"),
        "mover": create_mock_thread_object("mover_thread_for_args"),
        "observer": create_mock_thread_object("observer_thread_for_args"),
        "csv_consumer": create_mock_thread_object("csv_consumer_thread_for_args"),
        "uploader": create_mock_thread_object("uploader_thread_for_args"),
    }
    for t_mock in mock_threads_returned.values():
        t_mock._test_is_alive_flag = True
        t_mock.join.reset_mock()
        t_mock.start.reset_mock()

    inspectable_factories["create_scan_thread"].return_value = mock_threads_returned[
        "scanner"
    ]
    inspectable_factories[
        "create_file_move_thread"
    ].return_value = mock_threads_returned["mover"]
    inspectable_factories["create_csv_tailer_thread"].return_value = (
        mock_threads_returned["observer"],
        mock_threads_returned["csv_consumer"],
    )
    inspectable_factories[
        "create_uploader_thread"
    ].return_value = mock_threads_returned["uploader"]

    for name, mock_factory_func in inspectable_factories.items():
        monkeypatch.setattr(app_module, name, mock_factory_func)

    mock_app_context.shutdown_event.clear()
    run_app_thread = threading.Thread(target=app_module.run, args=(mock_app_context,))
    run_app_thread.start()
    time.sleep(0.2)

    assert run_app_thread.is_alive(), "app.run should be waiting on shutdown event"
    mock_app_context.shutdown_event.set()
    run_app_thread.join(timeout=SUT_THREAD_JOIN_TIMEOUT * 2)
    assert not run_app_thread.is_alive(), "app.run did not terminate as expected"

    config = mock_app_context.config

    inspectable_factories["create_scan_thread"].assert_called_once()
    scan_kwargs = inspectable_factories["create_scan_thread"].call_args.kwargs
    assert scan_kwargs["scan_directory_path"] == config.source_dir
    assert scan_kwargs["file_extension_to_scan"] == config.pcap_extension_no_dot
    assert scan_kwargs["scan_interval_seconds"] == config.scanner_check_seconds
    assert scan_kwargs["lost_timeout_seconds"] == config.lost_timeout_seconds
    assert (
        scan_kwargs["stuck_active_file_timeout_seconds"]
        == config.stuck_active_file_timeout_seconds
    )
    assert scan_kwargs["lost_file_queue"] is mock_queues["move_queue"]
    assert scan_kwargs["stop_event"] is mock_app_context.shutdown_event
    assert scan_kwargs["fs"] is mock_app_context.fs
    assert scan_kwargs["time_func"] is time.time
    assert scan_kwargs["monotonic_func"] is time.monotonic

    inspectable_factories["create_file_move_thread"].assert_called_once()
    mover_kwargs = inspectable_factories["create_file_move_thread"].call_args.kwargs
    assert mover_kwargs["source_dir_path"] == config.source_dir
    assert mover_kwargs["worker_dir_path"] == config.worker_dir
    assert mover_kwargs["poll_interval_seconds"] == config.move_poll_interval_seconds
    assert mover_kwargs["source_queue"] is mock_queues["move_queue"]
    assert mover_kwargs["stop_event"] is mock_app_context.shutdown_event
    assert mover_kwargs["fs"] is mock_app_context.fs
    assert mover_kwargs["sleep_func"] is time.sleep

    inspectable_factories["create_csv_tailer_thread"].assert_called_once()
    csv_kwargs = inspectable_factories["create_csv_tailer_thread"].call_args.kwargs
    assert csv_kwargs["csv_directory_to_watch"] == config.csv_dir
    assert csv_kwargs["csv_file_extension_no_dot"] == config.csv_extension_no_dot
    assert csv_kwargs["event_queue"] is mock_queues["tailer_queue"]
    assert csv_kwargs["move_queue"] is mock_queues["move_queue"]
    assert csv_kwargs["stop_event"] is mock_app_context.shutdown_event
    assert csv_kwargs["fs"] is mock_app_context.fs
    assert csv_kwargs["file_scanner"] is mock_app_context.file_scanner
    assert csv_kwargs["poll_interval"] == config.event_queue_poll_timeout_seconds

    inspectable_factories["create_uploader_thread"].assert_called_once()
    uploader_kwargs = inspectable_factories["create_uploader_thread"].call_args.kwargs
    expected_op_settings = UploaderOperationalSettings(
        worker_dir_path=config.worker_dir,
        uploaded_dir_path=config.uploaded_dir,
        dead_letter_dir_path=config.dead_letter_dir,
        file_extension_to_scan=config.pcap_extension_no_dot,
        poll_interval_seconds=config.uploader_poll_interval_seconds,
        heartbeat_interval_seconds=config.heartbeat_target_interval_s,
    )
    expected_sender_settings = SenderConnectionConfig(
        remote_host_url=config.remote_host_url,
        request_timeout_seconds=config.request_timeout,
        verify_ssl=config.verify_ssl,
        initial_backoff_seconds=config.initial_backoff,
        max_backoff_seconds=config.max_backoff,
    )
    assert uploader_kwargs["uploader_op_settings"] == expected_op_settings
    assert uploader_kwargs["sender_conn_config"] == expected_sender_settings
    assert uploader_kwargs["stop_event"] is mock_app_context.shutdown_event
    assert uploader_kwargs["fs"] is mock_app_context.fs
    assert uploader_kwargs["http_client"] is mock_app_context.http_client
    assert uploader_kwargs["file_scanner_impl"] is scan_directory_and_filter
    assert uploader_kwargs["safe_file_mover_impl"] is move_file_safely_impl

    for thread_mock_obj in mock_threads_returned.values():
        thread_mock_obj.start.assert_called_once()
        thread_mock_obj.join.assert_called_once_with(timeout=SUT_THREAD_JOIN_TIMEOUT)
