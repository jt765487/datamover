import signal
import logging
from functools import partial

from datamover.startup_code.context import AppContext

logger = logging.getLogger(__name__)


def handle_signal(context: AppContext, signum: int, _frame) -> None:
    """Signal handler: set shutdown_event once."""
    try:
        name = signal.Signals(signum).name
    except ValueError:
        name = f"SIGNAL {signum}"

    # Only trigger once
    if not context.shutdown_event.is_set():
        logger.warning(f"Got {name} ({signum}); initiating shutdown")
        try:
            context.shutdown_event.set()
        except Exception:
            logger.exception(f"Error setting shutdown_event for {name} ({signum})")


def install_signal_handlers(context: AppContext) -> None:
    """Attach SIGINT and SIGTERM to our handle_signal via functools.partial."""
    handler = partial(handle_signal, context)
    for sig in (signal.SIGINT, signal.SIGTERM):
        old_handler = signal.signal(sig, handler)
        logger.debug(
            f"Installed shutdown handler for {signal.Signals(sig).name}: replaced {old_handler}"
        )
