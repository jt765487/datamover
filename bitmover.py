import logging
import platform
import sys
from pathlib import Path
from time import sleep

from datamover.startup_code.cli import parse_args
from datamover.file_functions.create_directories import create_directories
from datamover.startup_code.load_config import load_config, ConfigError
from datamover.startup_code.context import build_context
from datamover.startup_code.logger_setup import (
    LoggingConfigurationError,
    setup_logging,
)
from datamover.startup_code.signal import install_signal_handlers
from datamover.app import run, AppRunFailureError, AppSetupError

# For sysexits.h codes - for systemd
EX_OK = 0  # successful termination
EX_USAGE = 64  # command line usage error
EX_UNAVAILABLE = 69  # service unavailable
EX_SOFTWARE = 70  # internal software error
EX_OSERR = 71  # system error (e.g., can't fork)
EX_TEMPFAIL: int = 75  # temp failure; user is invited to retry
EX_CONFIG = 78  # configuration error


def main_entrypoint():
    """
    Main function to initialize and run the application.
    """
    # 0. Platform Check
    if platform.system() != "Linux":
        # This is a fundamental requirement. No logging yet.
        print(
            f"FATAL: {Path(__file__).name} requires Linux. Current platform: {platform.system()}",
            file=sys.stderr,
        )
        sys.exit(EX_UNAVAILABLE)  # Service unavailable on this platform

    # 1. Parse command-line arguments
    args = None
    try:
        args = parse_args()
    except Exception as e:  # Catch-all for unexpected parsing errors
        print(
            f"CRITICAL: Unexpected error parsing command line arguments: {e}",
            file=sys.stderr,
        )
        sys.exit(EX_USAGE)

    # 2. Load application configuration
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(
            f"CRITICAL: Failed to load configuration from '{args.config}': {e}",
            file=sys.stderr,
        )
        sys.exit(EX_CONFIG)
    except Exception as e:
        print(
            f"CRITICAL: An unexpected error occurred while loading configuration from '{args.config}': {e}",
            file=sys.stderr,
        )
        sys.exit(EX_CONFIG)  # Still a config-related failure

    # 3. Configure logging
    try:
        console_log_level = logging.DEBUG if args.dev else logging.INFO
        setup_logging(
            log_file_dir=cfg.logger_dir,
            file_level=logging.DEBUG,
            console_level=console_log_level,
        )
    except LoggingConfigurationError as e:
        print(f"CRITICAL: Failed to configure logging: {e}", file=sys.stderr)
        sys.exit(EX_CONFIG)  # Logging is part of the essential config
    except Exception as e:
        print(
            f"CRITICAL: An unexpected error during logging setup using log_file_dir '{cfg.logger_dir}': {e}",
            file=sys.stderr,
        )
        sys.exit(EX_CONFIG)

    logger = logging.getLogger("datamover.main")
    logger.info("Application starting...")
    logger.info("Logging configured. Log directory: %s", cfg.logger_dir)
    logger.info("Configuration loaded successfully from %s", args.config)
    logger.debug("Dev mode: %s", args.dev)

    # 4. Build context
    context = None
    try:
        context = build_context(cfg)
        logger.info("Application context built.")
        logger.debug(
            "Context details: %s", context
        )  # Be careful logging full context if it contains secrets
    except Exception as e:
        logger.critical("Failed to build application context: %s", e, exc_info=True)
        sys.exit(EX_CONFIG)  # Context is vital setup

    # 5. Install signal handlers
    try:
        install_signal_handlers(context)
        logger.info("Signal handlers installed.")
    except Exception as e:
        logger.critical("Failed to install signal handlers: %s", e, exc_info=True)
        sys.exit(EX_SOFTWARE)  # Internal error if this fails

    # 6. Ensure the base directory exists and create operational directories
    try:
        if not context.fs.exists(context.config.base_dir):
            logger.critical(
                "Base directory %s does not exist and is required. Please create it or check configuration.",
                context.config.base_dir,
            )
            sys.exit(EX_CONFIG)  # Base dir is config dependent

        create_directories(cfg=context.config, fs=context.fs)
        logger.info(
            "Required operational directories verified/created under %s.",
            context.config.base_dir,
        )
    except ConfigError as e:  # create_directories might raise this for same-fs check
        logger.critical(
            "Directory setup failed due to configuration issue: %s", e, exc_info=True
        )
        sys.exit(EX_CONFIG)
    except OSError as e:
        logger.critical(
            "Directory setup failed due to OS error (e.g., permissions, disk full): %s",
            e,
            exc_info=True,
        )
        sys.exit(EX_OSERR)  # OS level error
    except Exception as e:
        logger.critical("Unexpected error during directory setup: %s", e, exc_info=True)
        sys.exit(EX_SOFTWARE)  # Unexpected internal

    # 7. Run the main application logic
    logger.info("Starting application run loop...")
    try:
        run(context)
        # If run() completes without exception, it means a graceful shutdown occurred
        # (e.g., shutdown_event was set by signal handler and loop exited)
        logger.info("Application run loop completed gracefully.")
        sys.exit(EX_OK)

    except KeyboardInterrupt:  # Should be caught by signal handlers but as a fallback
        logger.info(
            "Keyboard interrupt received directly in main. Initiating shutdown..."
        )
        if (
            context
            and hasattr(context, "shutdown_event")
            and not context.shutdown_event.is_set()
        ):
            context.shutdown_event.set()
        # Allow app.run() to hopefully finish its finally block.
        # The exit code will depend on how app.run() then exits.
        # If it handles the shutdown_event cleanly and returns, we'd hit EX_OK above.
        # If it re-raises or another error occurs, those will be caught below.
        # For safety, assume it's a temporary issue if it gets here.
        sys.exit(
            EX_TEMPFAIL
        )  # Or EX_OK if confident run() will handle it to clean exit

    except AppSetupError as e:  # Setup failure within app.run()
        logger.critical(
            "Application run failed during its internal setup phase: %s. A restart is unlikely to resolve this.",
            e,
            exc_info=True,
        )
        sys.exit(EX_CONFIG)  # Treat as a configuration/setup issue

    except (
        AppRunFailureError
    ) as e:  # Operational failure (e.g. health check), likely restartable
        logger.critical(
            "Application run failed due to a critical operational error: %s. Exiting to allow restart.",
            e,
            exc_info=True,
        )
        sys.exit(EX_TEMPFAIL)  # Standard "temporary failure, try again" code

    except Exception as e:  # Catch all other unexpected exceptions from run()
        logger.critical(
            "Fatal unhandled exception in main application run loop: %s",
            e,
            exc_info=True,
        )
        if (
            context
            and hasattr(context, "shutdown_event")
            and not context.shutdown_event.is_set()
        ):
            context.shutdown_event.set()  # Attempt to signal threads
            sleep(1)  # Allow a little time for shutdown event to propagate
        sys.exit(EX_SOFTWARE)  # General internal software error


# Guard for execution
if __name__ == "__main__":
    main_entrypoint()
