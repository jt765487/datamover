import copy
import datetime
import json
import logging
import logging.config
import sys
from pathlib import Path
from typing import Any, Optional, Union

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


def _generate_utc_iso_timestamp(record: logging.LogRecord) -> str:
    """Generates an ISO 8601 formatted timestamp in UTC."""
    dt = datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
    iso = dt.isoformat(timespec="milliseconds")
    if iso.endswith("+00:00"):
        return iso[:-6] + "Z"
    return iso


class JSONFormatter(logging.Formatter):
    """Custom Formatter for JSON output."""

    def __init__(
        self, fmt_keys: Optional[dict[str, str]] = None, datefmt: Optional[str] = None
    ):
        super().__init__(datefmt=datefmt)
        self.fmt_keys = fmt_keys.copy() if fmt_keys else {}

    def _prepare_log_dict(self, record: logging.LogRecord) -> dict[str, Any]:
        data: dict[str, Any] = {}
        log_message = record.getMessage()
        actual_exc_info = record.exc_info
        if actual_exc_info is True:  # pragma: no cover
            actual_exc_info = sys.exc_info()

        fmt_keys_values = self.fmt_keys.values()
        should_format_exc_info_by_default = (
            actual_exc_info
            and actual_exc_info[0] is not None
            and "exc_info" not in fmt_keys_values
        )
        should_format_stack_info_by_default = (
            record.stack_info is not None and "stack_info" not in fmt_keys_values
        )

        if self.fmt_keys:
            for key, record_attr_name in self.fmt_keys.items():
                if record_attr_name == "asctime":
                    data[key] = _generate_utc_iso_timestamp(record)
                elif record_attr_name == "message":
                    data[key] = log_message
                elif record_attr_name == "exc_info":
                    if actual_exc_info and actual_exc_info[0] is not None:
                        data[key] = self.formatException(actual_exc_info)
                elif record_attr_name == "stack_info":
                    if record.stack_info is not None:
                        data[key] = self.formatStack(record.stack_info)
                elif hasattr(record, record_attr_name):
                    val = getattr(record, record_attr_name)
                    if not callable(val):
                        data[key] = val
        else:
            data = {
                "timestamp": _generate_utc_iso_timestamp(record),
                "level": record.levelname,
                "message": log_message,
                "logger": record.name,
                "module": record.module,
                "funcName": record.funcName,
                "lineno": record.lineno,
            }

        if "message" not in data and "message" not in fmt_keys_values:
            data["message"] = log_message
        if should_format_exc_info_by_default and "exception" not in data:
            data["exception"] = self.formatException(actual_exc_info)  # type: ignore[arg-type]
        if should_format_stack_info_by_default and "stack_info" not in data:
            assert record.stack_info is not None
            data["stack_info"] = self.formatStack(record.stack_info)

        current_keys_in_data = set(data.keys())
        for record_attr_name, record_attr_value in record.__dict__.items():
            if (
                record_attr_name not in LOG_RECORD_BUILTIN_ATTRS
                and record_attr_name not in fmt_keys_values
                and record_attr_name not in current_keys_in_data
            ):
                if not callable(record_attr_value):
                    data[record_attr_name] = record_attr_value
        return data

    def format(self, record: logging.LogRecord) -> str:
        log_dict = self._prepare_log_dict(record)
        return json.dumps(log_dict, default=str)


class LoggingConfigurationError(Exception):
    """Custom exception for errors during logging setup."""

    pass


DEFAULT_LOG_FILENAME = "app.log.jsonl"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

BASE_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "dev_console": {
            "format": "%(asctime)s %(levelname)-8s [%(name)s:%(lineno)s] %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
        "json_file": {
            # <-- fully‐qualified path into your installed package
            "()": "datamover.startup_code.logger_setup.JSONFormatter",
            "fmt_keys": {
                "timestamp": "asctime",
                "thread_name": "threadName",
                "level": "levelname",
                "message": "message",
                "logger": "name",
                "function": "funcName",
                "line": "lineno",
            },
        },
    },
    "handlers": {
        "file_json": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "json_file",
            "filename": DEFAULT_LOG_FILENAME,
            "maxBytes": MAX_BYTES,
            "backupCount": BACKUP_COUNT,
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
        # <-- fully‐qualified module names
        "datamover.file_functions.gather_entry_data": {"level": "INFO"},
        "datamover.file_functions.scan_directory_and_filter": {"level": "INFO"},
        "watchdog": {"level": "INFO"},
    },
    "root": {
        "level": "DEBUG",
        "handlers": ["file_json", "console"],
    },
}


def _get_level_num(level_input: Union[int, str], param_name_for_error: str) -> int:
    if isinstance(level_input, str):
        level_upper = level_input.upper()
        numeric_level = logging.getLevelName(level_upper)
        if isinstance(numeric_level, str):
            numeric_level = logging._nameToLevel.get(level_upper)
        if numeric_level is None:
            try:
                potential_num = int(level_upper)
                if logging.getLevelName(potential_num).startswith("Level "):
                    raise LoggingConfigurationError(
                        f"Invalid numeric string for {param_name_for_error}: '{level_input}'. "
                        f"It does not map to a standard level name (e.g., DEBUG, INFO)."
                    )
                numeric_level = potential_num
            except ValueError:
                raise LoggingConfigurationError(
                    f"Invalid level string for {param_name_for_error}: '{level_input}'. "
                    f"Must be a standard level name (e.g., 'DEBUG') or a string representing a standard level number (e.g., '10')."
                )
        return numeric_level  # type: ignore
    elif isinstance(level_input, int):
        if logging.getLevelName(level_input).startswith("Level "):
            raise LoggingConfigurationError(
                f"Invalid numeric level for {param_name_for_error}: {level_input}. "
                f"It does not map to a standard level name (e.g., DEBUG, INFO)."
            )
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
    root_logger = logging.getLogger()
    original_root_handlers = list(root_logger.handlers)
    config_warnings: list[str] = []

    try:
        cfg: dict[str, Any]
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
            root_target_lvl_num = default_root_lvl_num
            root_cfg_handlers = cfg.get("root", {}).get("handlers", [])
            handler_levels_for_root_min = []
            if "console" in root_cfg_handlers and "console" in cfg.get("handlers", {}):
                handler_levels_for_root_min.append(console_target_lvl_num)
            if "file_json" in root_cfg_handlers and "file_json" in cfg.get(
                "handlers", {}
            ):
                handler_levels_for_root_min.append(file_target_lvl_num)
            if handler_levels_for_root_min:
                root_target_lvl_num = min(
                    root_target_lvl_num, *handler_levels_for_root_min
                )

        cfg.setdefault("root", {})["level"] = logging.getLevelName(root_target_lvl_num)
        if "console" in cfg.get(
            "handlers", {}
        ):  # Check if 'console' handler is defined
            cfg["handlers"]["console"]["level"] = logging.getLevelName(
                console_target_lvl_num
            )
        if "file_json" in cfg.get(
            "handlers", {}
        ):  # Check if 'file_json' handler is defined
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
            "Logging initialized: root=%s, console=%s, file_json=%s",
            cfg["root"]["level"],
            cfg.get("handlers", {}).get("console", {}).get("level", "N/A"),
            cfg.get("handlers", {}).get("file_json", {}).get("level", "N/A"),
        )

    except LoggingConfigurationError:
        raise
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as err:
        raise LoggingConfigurationError(f"Failed to initialize logging: {err}") from err
    except Exception as e:
        raise LoggingConfigurationError(
            f"An unexpected error occurred during logging setup: {e}"
        ) from e
