import datetime
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Any, Dict
from unittest.mock import patch
import threading

import pytest

from datamover.startup_code.logger_setup import (
    _generate_utc_iso_timestamp,
    JSONFormatter,
    _get_level_num,
    setup_logging,
    LoggingConfigurationError,
    DEFAULT_LOG_FILENAME,
)
from tests.test_utils.logging_helpers import find_log_record


# Helper to create LogRecord instances for testing
def make_record(
    msg: str,
    level: int = logging.INFO,
    name: str = "test_logger",
    created_ts: Optional[float] = None,
    exc_info: Any = None,
    stack_info: Any = None,
    extra: Optional[Dict[str, Any]] = None,
    pathname: str = __file__,
    lineno: int = 42,
    func: str = "test_func",
) -> logging.LogRecord:
    """
    Creates a LogRecord instance for testing purposes.
    Allows precise control over the 'created' timestamp and derived values.
    """
    _effective_created_ts: float = created_ts if created_ts is not None else time.time()

    _msecs_val: float = (_effective_created_ts - int(_effective_created_ts)) * 1000.0

    _relative_created_val: float
    if hasattr(logging, "_startTime") and isinstance(logging._startTime, (int, float)):
        _start_time_as_float: float = float(logging._startTime)
        _relative_created_val = (_effective_created_ts - _start_time_as_float) * 1000.0
    else:
        _relative_created_val = 0.0

    # Handle exc_info specifically for LogRecord constructor
    # Initialize with the provided exc_info (which could be an instance, a tuple, or None)
    # unless it's the boolean True, in which case we process it.
    processed_exc_info: Any = exc_info

    if exc_info is True:
        # If exc_info=True, capture current exception information by destructuring
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_type is not None:
            # An active exception exists, use its full tuple
            processed_exc_info = (exc_type, exc_value, exc_traceback)
        else:
            # No active exception, so exc_info=True means no actual exception info
            # LogRecord constructor expects None to signify no exception when exc_info was True
            # but no exception was found.
            processed_exc_info = None

    # Create the LogRecord instance
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=pathname,
        lineno=lineno,
        msg=msg,
        args=(),  # Assuming empty args for simplicity
        exc_info=processed_exc_info,  # Use the processed exc_info
        func=func,
    )

    # Override time-related attributes to match _effective_created_ts
    record.created = _effective_created_ts
    record.msecs = _msecs_val
    record.relativeCreated = _relative_created_val

    # Other attributes
    record.thread = threading.get_ident()
    record.threadName = "MainThread"
    record.process = os.getpid()

    if stack_info:
        record.stack_info = stack_info
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)

    return record


@pytest.fixture
def reset_logging_state():
    """Fixture to reset logging state before and after a test."""
    original_manager_loggerdict = logging.Logger.manager.loggerDict.copy()
    original_root_handlers = list(logging.root.handlers)
    original_root_level = logging.root.level
    original_manager_disable_level = logging.root.manager.disable  # type: ignore

    yield

    logging.shutdown()
    logging.Logger.manager.loggerDict.clear()
    logging.Logger.manager.loggerDict.update(original_manager_loggerdict)
    logging.root.handlers = original_root_handlers
    logging.root.setLevel(original_root_level)
    logging.root.manager.disable = original_manager_disable_level  # type: ignore

    # Clean up specific loggers created during tests if any
    for logger_name in list(logging.Logger.manager.loggerDict.keys()):
        logger = logging.getLogger(logger_name)
        if hasattr(logger, "handlers"):
            for handler in list(logger.handlers):  # Iterate over a copy
                logger.removeHandler(handler)
                if hasattr(handler, "close"):
                    handler.close()
    # Ensure root handlers are also cleaned up properly beyond just restoring the list
    for handler in list(logging.root.handlers):  # Iterate over a copy
        logging.root.removeHandler(handler)
        if hasattr(handler, "close"):
            handler.close()


# --- Test Cases for _generate_utc_iso_timestamp ---
def test_generate_utc_iso_timestamp_exact():
    record = make_record(
        msg="dummy msg for timestamp test", created_ts=1577836800.0
    )  # Added msg
    ts = _generate_utc_iso_timestamp(record)
    assert ts == "2020-01-01T00:00:00.000Z"


def test_generate_utc_iso_timestamp_with_milliseconds():
    record = make_record(msg="dummy msg", created_ts=1577836800.123)  # Added msg
    ts = _generate_utc_iso_timestamp(record)
    assert ts == "2020-01-01T00:00:00.123Z"


def test_generate_utc_iso_timestamp_milliseconds_rounding():
    record_truncates = make_record(
        msg="dummy msg", created_ts=1577836801.9996
    )  # Added msg
    ts_truncates = _generate_utc_iso_timestamp(record_truncates)
    assert ts_truncates == "2020-01-01T00:00:01.999Z"

    record_half_way = make_record(
        msg="dummy msg", created_ts=1577836801.9995
    )  # Added msg
    ts_half_way = _generate_utc_iso_timestamp(record_half_way)
    assert ts_half_way == "2020-01-01T00:00:01.999Z"

    record_round_down = make_record(
        msg="dummy msg", created_ts=1577836801.9994
    )  # Added msg
    ts_round_down = _generate_utc_iso_timestamp(record_round_down)
    assert ts_round_down == "2020-01-01T00:00:01.999Z"


def test_generate_utc_iso_timestamp_pre_epoch():
    try:
        pre_epoch_dt = datetime.datetime(
            1960, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
        )
        pre_epoch_ts_float = pre_epoch_dt.timestamp()
        record = make_record(
            msg="dummy msg", created_ts=pre_epoch_ts_float
        )  # Added msg
        ts = _generate_utc_iso_timestamp(record)
        assert ts == "1960-01-01T00:00:00.000Z"
    except OSError as e:  # pragma: no cover (OS dependent)
        pytest.skip(
            f"Skipping pre-epoch test due to OS limitation for timestamp(): {e}"
        )


# --- Test Cases for JSONFormatter ---


def test_jsonformatter_default_keys_and_values():
    fmt = JSONFormatter()
    record = make_record(
        msg="hello world",
        level=logging.DEBUG,
        created_ts=1577836800.0,  # 2020-01-01T00:00:00Z
        pathname=__file__,
        lineno=42,
        func="test_func",
    )
    formatted = fmt.format(record)
    data = json.loads(formatted)

    expected_keys = {
        "timestamp",
        "level",
        "message",
        "logger",
        "module",
        "function",
        "line",
    }
    assert expected_keys.issubset(set(data.keys()))
    assert data["timestamp"] == "2020-01-01T00:00:00.000Z"
    assert data["level"] == "DEBUG"
    assert data["message"] == "hello world"
    assert data["logger"] == "test_logger"
    assert data["module"] == Path(__file__).stem
    assert data["function"] == "test_func"
    assert data["line"] == 42


def test_jsonformatter_custom_fmt_keys():
    custom_keys = {
        "time": "asctime",
        "lvl": "levelname",
        "log_msg": "message",
        "source_logger": "name",
    }
    fmt = JSONFormatter(fmt_keys=custom_keys)
    record = make_record(msg="custom test", created_ts=1577836800.0)
    formatted = fmt.format(record)
    data = json.loads(formatted)

    assert set(data.keys()) == set(
        custom_keys.keys()
    )  # Check only custom keys are present
    assert data["time"] == "2020-01-01T00:00:00.000Z"
    assert data["lvl"] == "INFO"
    assert data["log_msg"] == "custom test"
    assert data["source_logger"] == "test_logger"


def test_jsonformatter_with_extras():
    fmt = JSONFormatter()
    extra_data = {"user_id": 123, "request_id": "abc"}
    record = make_record(
        msg="extra info test", extra=extra_data, created_ts=1577836800.0
    )
    formatted = fmt.format(record)
    data = json.loads(formatted)

    assert data["user_id"] == 123
    assert data["request_id"] == "abc"
    assert data["message"] == "extra info test"  # Default key
    assert data["timestamp"] == "2020-01-01T00:00:00.000Z"  # Default key


def test_jsonformatter_with_exception_info():
    fmt = JSONFormatter()
    try:
        raise ValueError("Test exception")
    except ValueError:
        exc_info_tuple = sys.exc_info()
        record = make_record(
            msg="exception test", exc_info=exc_info_tuple, created_ts=1577836800.0
        )

    formatted = fmt.format(record)
    data = json.loads(formatted)
    assert data["message"] == "exception test"
    assert JSONFormatter.DEFAULT_EXCEPTION_KEY in data
    assert "ValueError: Test exception" in data[JSONFormatter.DEFAULT_EXCEPTION_KEY]
    assert (
        "Traceback (most recent call last):"
        in data[JSONFormatter.DEFAULT_EXCEPTION_KEY]
    )


def test_jsonformatter_with_exception_info_true():
    fmt = JSONFormatter()
    try:
        raise TypeError("Another test exception")
    except TypeError:
        record = make_record(
            msg="exc_info true", exc_info=True, created_ts=1577836800.0
        )

    formatted = fmt.format(record)
    data = json.loads(formatted)
    assert JSONFormatter.DEFAULT_EXCEPTION_KEY in data
    assert (
        "TypeError: Another test exception" in data[JSONFormatter.DEFAULT_EXCEPTION_KEY]
    )


def test_jsonformatter_with_exception_instance():
    fmt = JSONFormatter()
    exc_instance = KeyError("A key error")  # This instance has no __traceback__
    record = make_record(
        msg="exc_info instance", exc_info=exc_instance, created_ts=1577836800.0
    )
    formatted = fmt.format(record)
    data = json.loads(formatted)

    assert JSONFormatter.DEFAULT_EXCEPTION_KEY in data
    formatted_exc_text = data[JSONFormatter.DEFAULT_EXCEPTION_KEY]

    # Check that the type and message are present
    assert "KeyError: 'A key error'" in formatted_exc_text

    # Check that "Traceback" is NOT present, as the instance had no traceback
    assert "Traceback" not in formatted_exc_text


def test_jsonformatter_with_stack_info():
    fmt = JSONFormatter()
    stack_info_str = "Fake stack trace"
    record = make_record(
        msg="stack info test", stack_info=stack_info_str, created_ts=1577836800.0
    )
    formatted = fmt.format(record)
    data = json.loads(formatted)
    assert data["message"] == "stack info test"
    assert JSONFormatter.DEFAULT_STACK_INFO_KEY in data
    assert data[JSONFormatter.DEFAULT_STACK_INFO_KEY] == stack_info_str


def test_jsonformatter_custom_exc_stack_keys():
    custom_keys = {
        "err_details": "exc_info",
        "call_stack": "stack_info",
        "the_message": "message",
    }
    fmt = JSONFormatter(fmt_keys=custom_keys)
    try:
        raise ValueError("Test exception for custom keys")
    except ValueError:
        exc_info_tuple = sys.exc_info()
        record = make_record(
            msg="custom exc/stack",
            exc_info=exc_info_tuple,
            stack_info="Custom stack",
            created_ts=1577836800.0,
        )
    formatted = fmt.format(record)
    data = json.loads(formatted)
    assert "err_details" in data
    assert "ValueError: Test exception for custom keys" in data["err_details"]
    assert "call_stack" in data
    assert data["call_stack"] == "Custom stack"
    assert data["the_message"] == "custom exc/stack"
    assert JSONFormatter.DEFAULT_EXCEPTION_KEY not in data
    assert JSONFormatter.DEFAULT_STACK_INFO_KEY not in data


def test_jsonformatter_no_exc_no_stack():
    fmt = JSONFormatter()
    record = make_record(msg="clean record", created_ts=1577836800.0)
    formatted = fmt.format(record)
    data = json.loads(formatted)
    assert JSONFormatter.DEFAULT_EXCEPTION_KEY not in data
    assert JSONFormatter.DEFAULT_STACK_INFO_KEY not in data


def test_jsonformatter_message_fallback_for_fmt_keys():
    fmt = JSONFormatter(fmt_keys={"ts": "asctime", "level_val": "levelname"})
    rec = make_record(msg="hey", created_ts=1577836800.0)
    data = json.loads(fmt.format(rec))
    assert (
        "message" not in data
    )  # message key should not appear if not in user_fmt_keys
    assert data["ts"] == "2020-01-01T00:00:00.000Z"
    assert "level_val" in data
    assert data["level_val"] == "INFO"


# --- Test Cases for _get_level_num ---
@pytest.mark.parametrize(
    "level_input, expected_output",
    [
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
        ("debug", logging.DEBUG),  # Case-insensitivity
        (logging.INFO, logging.INFO),
        ("10", logging.DEBUG),  # Numeric string for standard level
        ("30", logging.WARNING),
        (20, logging.INFO),
    ],
)
def test_get_level_num_valid_inputs(level_input, expected_output):
    assert _get_level_num(level_input, "param") == expected_output


def test_get_level_num_invalid_string():
    with pytest.raises(
        LoggingConfigurationError,
        match="Invalid level string for param: 'INVALIDLEVEL'",
    ):
        _get_level_num("INVALIDLEVEL", "param")


def test_get_level_num_invalid_numeric_string():
    # Change: Numeric strings that don't map to a standard level name are now accepted as integers.
    # The previous check `if logging.getLevelName(potential_num).startswith("Level ")`
    # was removed from _get_level_num in favor of direct int conversion.
    assert _get_level_num("17", "param") == 17  # Test that it now passes through as int


def test_get_level_num_invalid_integer_not_standard_level():
    # Change: Integers that don't map to a standard level name are accepted verbatim.
    # The previous check `if logging.getLevelName(level_input).startswith("Level ")`
    # was removed from _get_level_num.
    assert _get_level_num(15, "param") == 15  # Test that it now passes through


def test_get_level_num_type_error():
    with pytest.raises(
        TypeError, match="param must be an int or string, not <class 'list'>"
    ):
        _get_level_num([], "param")  # type: ignore


# --- Test Cases for setup_logging ---


def test_setup_logging_nonexistent_config_file(reset_logging_state):  # noqa: F841
    with pytest.raises(LoggingConfigurationError, match="Config file not found"):
        setup_logging(config_path=Path("/path/to/nonexistent/config.json"))


def test_setup_logging_invalid_json_config_file(tmp_path: Path, reset_logging_state):  # noqa: F841
    bad_json_file = tmp_path / "bad.json"
    bad_json_file.write_text("{ not_valid_json: True,, }")
    with pytest.raises(
        LoggingConfigurationError,
        match=r"Failed to initialize logging: Expecting property name enclosed in double quotes.*",
    ):
        setup_logging(config_path=bad_json_file)


def test_setup_logging_config_missing_handlers_key(tmp_path: Path, reset_logging_state):  # noqa: F841
    config_missing_handlers = {"version": 1, "root": {"level": "INFO"}}
    config_file = tmp_path / "missing_handlers.json"
    config_file.write_text(json.dumps(config_missing_handlers))
    setup_logging(config_path=config_file)
    assert logging.getLogger().level == logging.INFO


def test_setup_logging_invalid_handler_class_in_config(
    tmp_path: Path,
    reset_logging_state,  # noqa: F841
):
    invalid_handler_config = {
        "version": 1,
        "handlers": {"bad_handler": {"class": "non.existent.module.Handler"}},
        "root": {"handlers": ["bad_handler"], "level": "INFO"},
    }
    config_file = tmp_path / "invalid_handler.json"
    config_file.write_text(json.dumps(invalid_handler_config))
    with pytest.raises(
        LoggingConfigurationError,
        match=r"Failed to initialize logging: Unable to configure handler 'bad_handler'",
    ):
        setup_logging(config_path=config_file)


def test_setup_logging_non_writable_log_directory(tmp_path: Path, reset_logging_state):  # noqa: F841
    log_dir = tmp_path / "restricted_logs"
    with patch.object(Path, "mkdir", side_effect=OSError("Permission denied")):
        with pytest.raises(
            LoggingConfigurationError,
            match=f"Failed to create log directory {log_dir.resolve()}: Permission denied",
        ):
            setup_logging(log_file_dir=log_dir)


def test_setup_logging_absolute_filename_with_log_file_dir_warns(
    tmp_path: Path,
    reset_logging_state,
    caplog: pytest.LogCaptureFixture,  # noqa: F841
):
    caplog.set_level(logging.WARNING)
    abs_log_file = tmp_path / "absolute_test.log"
    handler_name = "abs_file_handler"
    config_with_abs_path = {
        "version": 1,
        "formatters": {"simple": {"format": "%(levelname)s:%(name)s:%(message)s"}},
        "handlers": {
            handler_name: {
                "class": "logging.FileHandler",
                "formatter": "simple",
                "filename": str(abs_log_file),
                "level": "WARNING",
            }
        },
        "root": {"handlers": [handler_name], "level": "WARNING"},
    }
    config_file = tmp_path / "abs_path_config.json"
    config_file.write_text(json.dumps(config_with_abs_path))
    ignored_log_dir = tmp_path / "ignored_dir"
    setup_logging(
        config_path=config_file, log_file_dir=ignored_log_dir, console_level="CRITICAL"
    )

    assert abs_log_file.exists()
    content = abs_log_file.read_text(encoding="utf-8")
    expected_warning_in_file = (
        f"log_file_dir='{ignored_log_dir}' is ignored for handler '{handler_name}'"
    )
    assert expected_warning_in_file in content

    warning_record = find_log_record(
        caplog, logging.WARNING, required_substrings=[expected_warning_in_file]
    )
    assert warning_record is not None, (
        "Warning about ignored log_file_dir not found in caplog"
    )
    assert warning_record.name == "datamover.startup_code.logger_setup"


def test_setup_logging_custom_formatter_fmt_keys_from_config(
    tmp_path: Path,
    reset_logging_state,  # noqa: F841
):
    log_dir = tmp_path / "custom_fmt_logs"
    log_file_name_only = "custom_output.jsonl"  # Relative name
    custom_fmt_keys = {
        "MY_TIMESTAMP": "asctime",
        "MY_LEVEL": "levelname",
        "MY_MESSAGE": "message",
        "MY_EXTRA_FIELD": "special_extra",
    }
    formatter_class_path = "datamover.startup_code.logger_setup.JSONFormatter"
    config_with_custom_fmt = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "my_custom_json_formatter": {
                "()": formatter_class_path,
                "fmt_keys": custom_fmt_keys,
            }
        },
        "handlers": {
            "custom_file_output": {
                "class": "logging.FileHandler",
                "formatter": "my_custom_json_formatter",
                "filename": log_file_name_only,  # Use only filename for relative path
                "level": "DEBUG",
                "encoding": "utf-8",
            }
        },
        "root": {"handlers": ["custom_file_output"], "level": "DEBUG"},
    }
    config_file_on_disk = tmp_path / "custom_fmt_config.json"
    config_file_on_disk.write_text(json.dumps(config_with_custom_fmt))

    setup_logging(
        config_path=config_file_on_disk, log_file_dir=log_dir, console_level="CRITICAL"
    )

    logger_to_test = logging.getLogger("custom_formatter_test_logger")
    logger_to_test.info(
        "Message for custom formatter.", extra={"special_extra": "value_for_extra"}
    )

    full_log_file_path = log_dir / log_file_name_only
    assert full_log_file_path.exists(), "Custom log file was not created."
    lines = full_log_file_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1, "Custom log file is empty."

    data = None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
            if entry.get("MY_MESSAGE") == "Message for custom formatter.":
                data = entry
                break
        except json.JSONDecodeError:
            continue

    assert data is not None, "Test message not found in custom log file"
    assert "MY_TIMESTAMP" in data
    assert data.get("MY_LEVEL") == "INFO"
    assert data.get("MY_MESSAGE") == "Message for custom formatter."
    assert data.get("MY_EXTRA_FIELD") == "value_for_extra"
    assert "message" not in data
    assert "level" not in data


def test_setup_logging_reinitialization_overrides_previous(
    tmp_path: Path,
    reset_logging_state,  # noqa: F841
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture,
):
    log_dir = tmp_path / "reinit_logs"
    caplog.set_level(logging.INFO)

    # First setup
    setup_logging(
        log_file_dir=log_dir, console_level="INFO", root_level="INFO", file_level="INFO"
    )
    _ = capsys.readouterr()

    root_logger = logging.getLogger()
    # Assuming 'console' handler is named in BASE_LOGGING_CONFIG
    console_handler_first = next(
        (h for h in root_logger.handlers if getattr(h, "name", None) == "console"), None
    )
    assert console_handler_first is not None, (
        "Console handler (named 'console') not found after first setup"
    )
    assert console_handler_first.level == logging.INFO

    first_init_log = find_log_record(
        caplog, logging.INFO, ["Logging initialized", "console=INFO"]
    )
    assert first_init_log is not None, (
        "First 'Logging initialized' (console=INFO) not captured by caplog"
    )
    caplog.clear()

    # Second setup
    setup_logging(
        log_file_dir=log_dir,
        console_level="DEBUG",
        root_level="DEBUG",
        file_level="DEBUG",
    )
    _ = capsys.readouterr()

    console_handler_second = next(
        (h for h in root_logger.handlers if getattr(h, "name", None) == "console"), None
    )
    assert console_handler_second is not None, (
        "Console handler (named 'console') not found after re-initialization"
    )
    assert console_handler_second.level == logging.DEBUG
    assert root_logger.level == logging.DEBUG

    second_init_log = find_log_record(
        caplog, logging.INFO, ["Logging initialized", "console=DEBUG"]
    )
    assert second_init_log is not None, (
        "Second 'Logging initialized' (console=DEBUG) not captured by caplog"
    )


def test_setup_logging_without_log_file_dir_for_relative_path_raises(
    reset_logging_state,  # noqa: F841
):
    test_config = {
        "version": 1,
        "handlers": {
            "file": {"class": "logging.FileHandler", "filename": "relative.log"}
        },
        "root": {"handlers": ["file"], "level": "INFO"},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".json", encoding="utf-8"
    ) as tmp_file:
        json.dump(test_config, tmp_file)
        config_path_str = tmp_file.name
    config_path = Path(config_path_str)
    try:
        with pytest.raises(
            LoggingConfigurationError,
            match="uses a relative filename 'relative.log' but no log_file_dir was provided",
        ):
            setup_logging(config_path=config_path)
    finally:
        if config_path.exists():
            os.remove(config_path_str)


def test_setup_logging_with_base_config_without_log_file_dir_raises(
    reset_logging_state,  # noqa: F841
):
    with pytest.raises(
        LoggingConfigurationError,
        match=f"uses a relative filename '{DEFAULT_LOG_FILENAME}' but no log_file_dir was provided",
    ):
        setup_logging()


def test_setup_logging_creates_log_file_and_writes(
    tmp_path: Path,
    reset_logging_state,  # noqa: F841
    caplog: pytest.LogCaptureFixture,  # noqa: F841
):
    log_dir = tmp_path / "logs"
    setup_logging(
        log_file_dir=log_dir,
        console_level="CRITICAL",
        file_level="DEBUG",
        root_level="DEBUG",
    )

    logger = logging.getLogger("file_write_test." + __name__)
    logger.debug("debug message for file")
    logger.info("info message for file")

    log_file = log_dir / DEFAULT_LOG_FILENAME
    assert log_file.exists(), f"Log file {log_file} was not created."
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) >= 3, (
        f"Expected at least 3 log entries, found {len(lines)}. Content: {lines}"
    )

    entries = [json.loads(line) for line in lines]
    messages_in_file = {e.get("message") for e in entries}
    assert "debug message for file" in messages_in_file
    assert "info message for file" in messages_in_file
    assert any("Logging initialized" in e.get("message", "") for e in entries)


def test_setup_logging_with_config_path_writes_to_file(
    tmp_path: Path, reset_logging_state
):
    custom_file_name = "custom_test_log.jsonl"
    custom_log_file_path = tmp_path / custom_file_name
    formatter_class_path = "datamover.startup_code.logger_setup.JSONFormatter"

    cfg_for_test = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json_file_custom": {"()": formatter_class_path, "fmt_keys": None}
        },
        "handlers": {
            "specific_file_handler_custom": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",
                "formatter": "json_file_custom",
                "filename": str(custom_log_file_path),
                "maxBytes": 1024,
                "backupCount": 1,
                "encoding": "utf8",
            }
        },
        "loggers": {
            "my_app.module_under_test": {
                "level": "DEBUG",
                "handlers": ["specific_file_handler_custom"],
                "propagate": False,
            }
        },
        "root": {"level": "CRITICAL", "handlers": []},
    }
    config_file_on_disk = tmp_path / "test_logging_custom.json"
    config_file_on_disk.write_text(json.dumps(cfg_for_test), encoding="utf-8")

    setup_logging(config_path=config_file_on_disk, console_level="CRITICAL")

    logger_to_test = logging.getLogger("my_app.module_under_test")
    logger_to_test.debug("message from custom config to specific file")

    assert custom_log_file_path.exists()
    contents = custom_log_file_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) >= 1
    logged_json = json.loads(contents[0])
    assert logged_json.get("message") == "message from custom config to specific file"
    assert logged_json.get("level") == "DEBUG"
    assert not any("Logging initialized" in line for line in contents)


def test_jsonformatter_exc_info_true_branch():
    fmt = JSONFormatter()
    formatted = None
    try:
        raise RuntimeError("oops")
    except RuntimeError:
        rec = make_record(msg="dummy message for exc_info true", exc_info=True)
        formatted = fmt.format(rec)
    assert formatted is not None
    data = json.loads(formatted)
    assert "exception" in data
    assert "RuntimeError: oops" in data["exception"]


def test_setup_logging_root_level_override(tmp_path: Path, reset_logging_state):
    setup_logging(
        log_file_dir=tmp_path,
        root_level="ERROR",
        console_level="DEBUG",
        file_level="DEBUG",
    )
    assert logging.getLogger().level == logging.ERROR


def test_setup_logging_missing_handlers_ignores_overrides(
    tmp_path: Path, reset_logging_state
):
    formatter_class_path = "datamover.startup_code.logger_setup.JSONFormatter"
    cfg = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json_file": {"()": formatter_class_path, "fmt_keys": None}},
        "handlers": {},
        "root": {"handlers": [], "level": "INFO"},
    }
    cfg_file = tmp_path / "cfg_no_handlers.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    setup_logging(config_path=cfg_file, console_level="DEBUG", file_level="ERROR")
    assert logging.getLogger().level == logging.INFO

    # After setup_logging with root handlers [], and restoration of original (pytest) handlers,
    # the root logger should have at least pytest's handlers.
    # It should NOT have 'console' or 'file_json' from BASE_LOGGING_CONFIG.
    root_handlers = logging.getLogger().handlers
    assert not any(getattr(h, "name", None) == "console" for h in root_handlers)
    assert not any(getattr(h, "name", None) == "file_json" for h in root_handlers)
    # Check that it has some handlers (e.g., pytest's)
    assert len(root_handlers) > 0, "Root logger should have pytest's capture handlers"
