import signal
import logging
from functools import partial
from unittest.mock import MagicMock
import threading

import pytest

# Functions under test
from datamover.startup_code.signal import handle_signal, install_signal_handlers
from datamover.startup_code.context import AppContext

from tests.test_utils.logging_helpers import find_log_record


def make_context(side_effects=None, set_exc=None):
    """Helper: create a mock AppContext with a MagicMock for shutdown_event."""
    mock_event = MagicMock(name="mock_shutdown_event", spec=threading.Event)

    # Configure is_set side effects
    if side_effects is not None:
        mock_event.is_set.side_effect = side_effects
    else:
        mock_event.is_set.return_value = False  # Default behavior

    # Configure set exception
    if set_exc is not None:
        mock_event.set.side_effect = set_exc

    context = MagicMock(spec=AppContext, name="mock_app_context")
    context.shutdown_event = mock_event
    return context, mock_event


@pytest.mark.parametrize("initial_signal_num_to_test", [signal.SIGTERM, signal.SIGINT])
def test_handle_signal_sets_event_once_and_logs_for_known_signals(
    initial_signal_num_to_test: signal.Signals, caplog: pytest.LogCaptureFixture
):
    """
    Tests that handle_signal sets the shutdown_event on the first call
    (for both SIGINT and SIGTERM as initial signals) and logs appropriately.
    It also checks that a subsequent, different signal does not re-set the event
    or log new warnings.
    """
    # Arrange: Event is initially not set, then becomes set.
    # is_set() will be called twice in each parameterized run:
    # 1. For the initial_signal_num_to_test (should return False to trigger set())
    # 2. For the subsequent_signal_num (should return True as event is now set)
    context, mock_event = make_context(side_effects=[False, True])
    caplog.set_level(logging.WARNING)

    initial_signal_name = signal.Signals(initial_signal_num_to_test).name

    # Act - First call (with the parameterized initial_signal_num_to_test)
    handle_signal(context, initial_signal_num_to_test, _frame=None)

    # Assert - First call
    mock_event.set.assert_called_once()
    record = find_log_record(
        caplog,
        logging.WARNING,
        [
            f"Got {signal.Signals(initial_signal_num_to_test).name}",
            str(initial_signal_num_to_test.value),   # use .value here
            "initiating shutdown",
        ],
    )
    assert record is not None, (
        f"Warning log for initial signal {signal.Signals(initial_signal_num_to_test).name} not found."
    )

    # Arrange - Second call (with the *other* signal, event is now "set")
    caplog.clear()  # Clear logs from the first call
    # mock_event.set.reset_mock() # No, we want to assert it's still only called once in total

    # Determine the subsequent signal to test idempotency
    subsequent_signal_num = (
        signal.SIGINT
        if initial_signal_num_to_test == signal.SIGTERM
        else signal.SIGTERM
    )

    # Act - Second call
    handle_signal(context, subsequent_signal_num, _frame=None)

    # Assert - Second call
    mock_event.set.assert_called_once()  # Total calls to set() should remain 1
    assert not caplog.records, (
        f"Expected no new log records on second signal ({signal.Signals(subsequent_signal_num).name}) when event already set by {initial_signal_name}"
    )

    # Verify is_set was called twice in total for this parameterized run
    assert mock_event.is_set.call_count == 2


def test_handle_signal_unknown_signal_number(caplog: pytest.LogCaptureFixture):
    """
    Tests that handle_signal uses a fallback name in the log message
    if an unknown signal number is received.
    """
    context, mock_event = make_context(side_effects=[False, True])
    caplog.set_level(logging.WARNING)
    unknown_sig_num = 9999

    handle_signal(context, unknown_sig_num, _frame=None)

    mock_event.set.assert_called_once()
    record = find_log_record(
        caplog,
        logging.WARNING,
        [f"Got SIGNAL {unknown_sig_num}", str(unknown_sig_num), "initiating shutdown"],
    )
    assert record is not None, "Expected warning log for unknown signal not found."


def test_handle_signal_set_raises_exception_logs_exception(
    caplog: pytest.LogCaptureFixture,
):
    """
    Tests that if context.shutdown_event.set() raises an exception,
    handle_signal catches it, logs it (with exception info), and does not crash.
    """
    exception_to_raise = RuntimeError("boom from set")
    context, mock_event = make_context(side_effects=[False], set_exc=exception_to_raise)
    caplog.set_level(logging.ERROR)
    test_signal_num = signal.SIGINT
    test_signal_name = signal.Signals(test_signal_num).name

    handle_signal(context, test_signal_num, _frame=None)

    mock_event.set.assert_called_once()
    record = find_log_record(
        caplog,
        logging.ERROR,
        [
            f"Error setting shutdown_event for {signal.Signals(test_signal_num).name}",
            str(test_signal_num.value),            # and here
        ],
    )
    assert record is not None, "Expected error log when event.set() fails not found."
    assert record.exc_info is not None, "Exception info should be logged."
    assert record.exc_info[0] is type(exception_to_raise)


def test_handle_signal_noop_when_already_set(caplog: pytest.LogCaptureFixture):
    """
    Tests that if the shutdown_event is already set, handle_signal does not
    call set() again and does not log a new warning.
    """
    context, mock_event = make_context(side_effects=[True, True])
    caplog.set_level(logging.WARNING)

    handle_signal(context, signal.SIGINT, _frame=None)

    mock_event.set.assert_not_called()
    assert not caplog.records, "Expected no new log records when event is already set."


def test_install_signal_handlers_registers_and_logs_and_handler_calls_correctly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """
    Comprehensive test for install_signal_handlers:
    - Verifies correct signals (SIGINT, SIGTERM) are registered.
    - Verifies debug logs for installation.
    - Verifies the registered handlers are partials correctly calling the main handle_signal.
    """
    mock_actual_handle_signal_func = MagicMock(name="mock_actual_handle_signal_func")
    monkeypatch.setattr(
        "datamover.startup_code.signal.handle_signal", mock_actual_handle_signal_func
    )

    registered_signal_handlers = {}
    original_handlers_replaced = {}

    def fake_signal_registration(sig_num, handler_func):
        registered_signal_handlers[sig_num] = handler_func
        old_handler_name = f"old_handler_for_signal_{sig_num}"
        original_handlers_replaced[sig_num] = old_handler_name
        return old_handler_name

    monkeypatch.setattr(signal, "signal", fake_signal_registration)
    caplog.set_level(logging.DEBUG)

    mock_install_context = MagicMock(name="mock_install_context")
    mock_install_context.shutdown_event = MagicMock(
        spec=threading.Event, name="event_for_install"
    )

    install_signal_handlers(mock_install_context)

    assert set(registered_signal_handlers.keys()) == {signal.SIGINT, signal.SIGTERM}
    for sig_num_registered in (signal.SIGINT, signal.SIGTERM):
        signal_name = signal.Signals(sig_num_registered).name
        expected_log_message_part = (
            f"Installed shutdown handler for {signal_name}: "
            f"replaced {original_handlers_replaced[sig_num_registered]}"
        )
        assert (
            find_log_record(caplog, logging.DEBUG, [expected_log_message_part])
            is not None
        )

    for sig_num_to_test, registered_handler in registered_signal_handlers.items():
        assert isinstance(registered_handler, partial), (
            f"Handler for {signal.Signals(sig_num_to_test).name} is not a partial."
        )

        assert registered_handler.func is mock_actual_handle_signal_func, (
            f"Partial for {signal.Signals(sig_num_to_test).name} is not wrapping the mocked handle_signal."
        )

        assert registered_handler.args[0] is mock_install_context, (
            f"Context not correctly bound in partial for {signal.Signals(sig_num_to_test).name}"
        )

        dummy_frame = object()
        registered_handler(sig_num_to_test, dummy_frame)

        mock_actual_handle_signal_func.assert_any_call(
            mock_install_context, sig_num_to_test, dummy_frame
        )

    assert mock_actual_handle_signal_func.call_count == len(registered_signal_handlers)
