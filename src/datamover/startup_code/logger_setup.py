import copy
import datetime
import json
import logging
import logging.config
import sys
import traceback  # For the optional suggestion in setup_logging
from pathlib import Path
from typing import Any, Dict, Optional, Union, Tuple, Type  # For type hints

# A set of built-in LogRecord attributes.
LOG_RECORD_BUILTIN_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}

# Logger default configurations
DEFAULT_LOG_FILENAME = "app.log.jsonl"
DEFAULT_AUDIT_LOG_FILENAME = "audit.log.jsonl"

DEBUG_LOG_MAX_BYTES = 10 * 1024 * 1024
DEBUG_LOG_BACKUP_COUNT = 5

AUDIT_LOG_MAX_BYTES = 50 * 1024 * 1024
AUDIT_LOG_BACKUP_COUNT = 20


# --- JSONFormatter and its helpers ---

# Simplified type alias for exc_info tuple
ExcInfoTupleType = Tuple[
    Type[BaseException], BaseException, Any
]  # Standard sys.exc_info() tuple
ExcInfoNormalizedType = Optional[ExcInfoTupleType]

# A clear alias for the one shape we accept
NormalizedExcInfo = Tuple[Type[BaseException], BaseException, Any]


def _generate_utc_iso_timestamp(record: logging.LogRecord) -> str:
    """Generates an ISO 8601 formatted timestamp in UTC."""
    dt = datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
    iso = dt.isoformat(timespec="milliseconds")
    if iso.endswith("+00:00"):
        return iso[:-6] + "Z"
    return iso


def _normalize_exc_info(record: logging.LogRecord) -> Optional[NormalizedExcInfo]:
    """
    Normalize a LogRecord’s exc_info into a consistent 3-tuple or None.

    Many parts of the logging API allow `record.exc_info` to come in different forms:
      - `None` or `False` ⇒ no exception
      - `True` ⇒ “include the current exception” (from sys.exc_info())
      - a 3-tuple (exc_type, exc_value, traceback)
      - an actual Exception instance

    This helper coalesces all valid inputs into exactly one shape:
      (`exc_type: Type[BaseException]`, `exc_value: BaseException`, `tb: Any`)
    or `None` if no usable exception data was found.

    By performing:
      1. Early exits on falsy inputs
      2. A special case for `True` via `sys.exc_info()`
      3. Wrapping a lone Exception instance into a 3-tuple
      4. A runtime check that it's a length-3 tuple
      5. Destructuring (avoiding raw `raw[0]` indexing on an unknown type)
      6. A final guard that the first element is really a subclass of BaseException

    We both:
      - Guarantee a single, statically typed return shape for downstream code, and
      - Satisfy type-checkers (mypy/pyright) so they no longer warn about indexing
        arbitrary `Any` values.

    Returns:
        A tuple (exc_type: Type[BaseException], exc_value: BaseException, tb: Any)
        if valid exception info is present; otherwise None.
    """
    raw = record.exc_info

    # 1) Early bail on “nothing here”
    if not raw:
        return None

    # 2) If they passed True, grab the current exception
    if raw is True:
        raw = sys.exc_info()

    # 3) If they passed an exception instance, wrap it
    elif isinstance(raw, BaseException):
        raw = (type(raw), raw, raw.__traceback__)

    # 4) If it still isn’t a 3-tuple, give up
    if not (isinstance(raw, tuple) and len(raw) == 3):
        return None

    # At this point mypy/pyright knows `raw: Tuple[Any, Any, Any]`.
    # Now destructure—no more [0] indexing on a fuzzy type:
    cls, val, tb = raw

    # 5) Finally, check the first element is really an exception *type*
    if not (isinstance(cls, type) and issubclass(cls, BaseException)):
        return None

    # Now `cls,val,tb` is exactly our NormalizedExcInfo
    return cls, val, tb


class JSONFormatter(logging.Formatter):
    """
    Custom Formatter for JSON output.
    Incorporates QA suggestions for simplification, type safety, and maintainability.
    """

    DEFAULT_FMT_KEYS: Dict[str, str] = {
        "timestamp": "asctime",
        "level": "levelname",
        "message": "message",
        "logger": "name",
        "module": "module",  # Retained 'module' as a useful default. Can be removed if too verbose.
        "function": "funcName",
        "line": "lineno",
    }
    DEFAULT_EXCEPTION_KEY: str = "exception"
    DEFAULT_STACK_INFO_KEY: str = "stack_info"

    def __init__(
        self, fmt_keys: Optional[Dict[str, str]] = None, datefmt: Optional[str] = None
    ):
        super().__init__(datefmt=datefmt)
        self.user_fmt_keys: Optional[Dict[str, str]] = (
            fmt_keys.copy() if fmt_keys is not None else None
        )

    def _prepare_log_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        log_message: str = record.getMessage()

        normalized_exc_info = _normalize_exc_info(record)

        # Determine effective format keys: user-supplied or default
        effective_fmt_keys = (
            self.user_fmt_keys
            if self.user_fmt_keys is not None
            else self.DEFAULT_FMT_KEYS
        )

        # Set of LogRecord attribute names that have been explicitly mapped by effective_fmt_keys.
        # This helps avoid double-processing by the "extras" collection step.
        # Also include standard 'exc_info' and 'stack_info' if they will be handled separately.
        processed_record_attributes: set[str] = set(effective_fmt_keys.values())
        if normalized_exc_info:
            processed_record_attributes.add("exc_info")
        if record.stack_info:
            processed_record_attributes.add("stack_info")

        # Populate data using a dictionary comprehension for mapped fields
        for output_key, record_attr_name in effective_fmt_keys.items():
            if record_attr_name == "asctime":
                data[output_key] = _generate_utc_iso_timestamp(record)
            elif record_attr_name == "message":
                data[output_key] = log_message
            # Explicit 'exc_info' or 'stack_info' in fmt_keys are handled here.
            # If they are NOT in fmt_keys, they'll be handled by the default attachment below.
            elif record_attr_name == "exc_info":
                if normalized_exc_info:
                    data[output_key] = self.formatException(normalized_exc_info)
            elif record_attr_name == "stack_info":
                if record.stack_info:
                    data[output_key] = self.formatStack(record.stack_info)
            elif hasattr(record, record_attr_name):
                value = getattr(record, record_attr_name)
                # Only add if the value is not callable (to avoid methods)
                # and primitive enough or let json.dumps handle it with default=str
                if not callable(value):
                    data[output_key] = value

        # Add default exception and stack information if they exist and
        # were NOT explicitly mapped by `effective_fmt_keys`.
        # Check if output keys for the default exception / stack would collide with user-defined keys.
        if normalized_exc_info and "exc_info" not in effective_fmt_keys.values():
            if (
                self.DEFAULT_EXCEPTION_KEY not in data
            ):  # Ensure the key is not already used
                data[self.DEFAULT_EXCEPTION_KEY] = self.formatException(
                    normalized_exc_info
                )

        if record.stack_info and "stack_info" not in effective_fmt_keys.values():
            if (
                self.DEFAULT_STACK_INFO_KEY not in data
            ):  # Ensure the key is not already used
                data[self.DEFAULT_STACK_INFO_KEY] = self.formatStack(record.stack_info)

        # Collect "extra" attributes from record.__dict__
        for attr_name, attr_value in record.__dict__.items():
            if (
                attr_name not in LOG_RECORD_BUILTIN_ATTRS
                and attr_name not in processed_record_attributes
                and attr_name
                not in data  # Check if the output key 'attr_name' is already used
                and not callable(attr_value)
            ):
                data[attr_name] = attr_value

        return data

    def format(self, record: logging.LogRecord) -> str:
        log_dict = self._prepare_log_dict(record)
        return json.dumps(log_dict, default=str)


# --- End of JSONFormatter ---

FORMATTER_CLASS_PATH = f"{__name__}.JSONFormatter"

BASE_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "dev_console": {
            "format": "%(asctime)s %(levelname)-8s [%(name)s:%(lineno)s] %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
        "json_file": {
            "()": FORMATTER_CLASS_PATH,
            "fmt_keys": JSONFormatter.DEFAULT_FMT_KEYS,  # Use the class default directly
        },
        "audit_json_file": {
            "()": FORMATTER_CLASS_PATH,
            "fmt_keys": {  # Audit logs often rely more on 'extra' fields
                "timestamp": "asctime",
                "level": "levelname",
                "message": "message",
                "logger_name": "name",  # Explicitly "logger_name" for audit
            },
        },
    },
    "handlers": {
        "file_json": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "json_file",
            "filename": DEFAULT_LOG_FILENAME,
            "maxBytes": DEBUG_LOG_MAX_BYTES,
            "backupCount": DEBUG_LOG_BACKUP_COUNT,
            "encoding": "utf8",
        },
        "audit_file_json": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "audit_json_file",
            "filename": DEFAULT_AUDIT_LOG_FILENAME,
            "maxBytes": AUDIT_LOG_MAX_BYTES,
            "backupCount": AUDIT_LOG_BACKUP_COUNT,
            "encoding": "utf8",
        },
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "dev_console",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "datamover.file_functions.gather_entry_data": {"level": "INFO"},
        "datamover.file_functions.scan_directory_and_filter": {"level": "INFO"},
        "watchdog": {"level": "INFO"},
        "datamover.upload_audit": {
            "handlers": ["audit_file_json"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
    "root": {
        "level": "DEBUG",
        "handlers": ["file_json", "console"],
    },
}


class LoggingConfigurationError(Exception):
    """Custom exception for errors during logging setup."""

    pass


def _get_level_num(level_input: Union[int, str], param_name_for_error: str) -> int:
    if isinstance(level_input, str):
        level_upper = level_input.upper()
        numeric_level = logging.getLevelName(level_upper)
        if not isinstance(numeric_level, int):
            try:
                numeric_level = int(level_upper)
                # No need for the `pass` here, the value is used directly.
            except ValueError:
                raise LoggingConfigurationError(
                    f"Invalid level string for {param_name_for_error}: '{level_input}'. "
                    f"Must be a standard level name (e.g., 'DEBUG') or a string representing a standard level number (e.g., '10')."
                )
        return numeric_level
    elif isinstance(level_input, int):
        return level_input
    raise TypeError(
        f"{param_name_for_error} must be an int or string, not {type(level_input)}"
    )


def setup_logging(
    *,
    config_path: Optional[Path] = None,
    log_file_dir: Optional[Path] = None,
    root_level: Optional[Union[int, str]] = None,
    console_level: Optional[Union[int, str]] = None,
    file_level: Optional[Union[int, str]] = None,
) -> None:
    # ... setup_logging logic (largely unchanged internally, but see exception handling) ...
    root_logger = logging.getLogger()
    original_root_handlers = list(root_logger.handlers)
    config_warnings: list[str] = []

    try:
        cfg: dict[str, Any] = {}
        if config_path:
            if not config_path.exists():
                raise LoggingConfigurationError(f"Config file not found: {config_path}")
            with config_path.open("rt", encoding="utf8") as fp:
                cfg = json.load(fp)
            cfg["disable_existing_loggers"] = False
        else:
            cfg = copy.deepcopy(BASE_LOGGING_CONFIG)

        for handler_name, handler_cfg_dict in cfg.get("handlers", {}).items():
            fname_str = handler_cfg_dict.get("filename")
            if not fname_str:
                continue
            original_path = Path(fname_str)
            if original_path.is_absolute():
                final_path = original_path.resolve()
                if log_file_dir:
                    config_warnings.append(
                        f"Warning: log_file_dir='{log_file_dir}' is ignored for handler '{handler_name}' as it uses an absolute path: '{fname_str}'"
                    )
            elif log_file_dir:
                final_path = (log_file_dir / original_path).resolve()
            else:
                raise LoggingConfigurationError(
                    f"Handler '{handler_name}' uses a relative filename '{fname_str}' but no log_file_dir was provided"
                )
            try:
                final_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise LoggingConfigurationError(
                    f"Failed to create log directory {final_path.parent}: {e}"
                ) from e
            handler_cfg_dict["filename"] = str(final_path)

        default_root_lvl_num = logging.INFO
        default_console_lvl_num = logging.INFO
        default_file_lvl_num = logging.DEBUG

        console_target_lvl_num = (
            _get_level_num(console_level, "console_level")
            if console_level is not None
            else default_console_lvl_num
        )
        file_target_lvl_num = (
            _get_level_num(file_level, "file_level")
            if file_level is not None
            else default_file_lvl_num
        )

        root_target_lvl_num: int
        if root_level is not None:
            root_target_lvl_num = _get_level_num(root_level, "root_level")
        else:
            root_cfg_handlers = cfg.get("root", {}).get("handlers", [])
            handler_levels_for_root_min = []
            if "console" in root_cfg_handlers and "console" in cfg.get("handlers", {}):
                handler_levels_for_root_min.append(console_target_lvl_num)
            if "file_json" in root_cfg_handlers and "file_json" in cfg.get(
                "handlers", {}
            ):
                handler_levels_for_root_min.append(file_target_lvl_num)

            effective_min_handler_level_for_root = (
                min(handler_levels_for_root_min)
                if handler_levels_for_root_min
                else default_root_lvl_num
            )
            root_target_lvl_num = min(
                default_root_lvl_num, effective_min_handler_level_for_root
            )

        cfg.setdefault("root", {})["level"] = logging.getLevelName(root_target_lvl_num)
        if "console" in cfg.get("handlers", {}):
            cfg["handlers"]["console"]["level"] = logging.getLevelName(
                console_target_lvl_num
            )
        if "file_json" in cfg.get("handlers", {}):
            cfg["handlers"]["file_json"]["level"] = logging.getLevelName(
                file_target_lvl_num
            )

        logging.config.dictConfig(cfg)

        current_root_handlers_after_dictconfig = set(root_logger.handlers)
        for original_handler in original_root_handlers:
            if original_handler not in current_root_handlers_after_dictconfig:
                root_logger.addHandler(original_handler)

        app_internal_logger = logging.getLogger(__name__)
        for warning_message in config_warnings:
            app_internal_logger.warning(warning_message)

        app_internal_logger.info(
            "Logging initialized: root=%s, console=%s (effective), file_json=%s (effective), audit_file_json=%s (handler)",
            logging.getLevelName(root_logger.getEffectiveLevel()),
            cfg.get("handlers", {}).get("console", {}).get("level", "N/A"),
            cfg.get("handlers", {}).get("file_json", {}).get("level", "N/A"),
            cfg.get("handlers", {}).get("audit_file_json", {}).get("level", "N/A"),
        )

    except LoggingConfigurationError:
        raise
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as err:
        raise LoggingConfigurationError(f"Failed to initialize logging: {err}") from err
    except Exception as e:
        # For truly unexpected errors during logging setup, print to stderr and include traceback
        sys.stderr.write(
            f"CRITICAL: An unexpected error occurred during logging setup: {e}\n"
        )
        traceback.print_exc(file=sys.stderr)  # Print stack trace to stderr
        raise LoggingConfigurationError(
            f"An unexpected error occurred during logging setup: {e}"
        ) from e
