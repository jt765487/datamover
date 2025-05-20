from configparser import (
    ConfigParser,
    MissingSectionHeaderError,
    ParsingError,
    NoOptionError,
)
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from datamover.file_functions.fs_mock import FS


class ConfigError(Exception):
    """Raised when the configuration is invalid or missing."""

    pass


@dataclass(frozen=True)
class Config:
    """Holds the application configuration, matching the new INI file structure."""

    # From [Directories]
    base_dir: Path
    logger_dir: Path

    # Derived from base_dir
    source_dir: Path
    worker_dir: Path
    uploaded_dir: Path
    dead_letter_dir: Path
    csv_dir: Path

    # From [Files]
    pcap_extension_no_dot: str
    csv_extension_no_dot: str

    # From [Mover]
    move_poll_interval_seconds: float

    # From [Scanner]
    scanner_check_seconds: float
    lost_timeout_seconds: float
    stuck_active_file_timeout_seconds: float

    # From [Tailer]
    event_queue_poll_timeout_seconds: float

    # From [Uploader]
    uploader_poll_interval_seconds: float
    heartbeat_target_interval_s: float
    remote_host_url: str
    request_timeout: float
    verify_ssl: bool
    initial_backoff: float
    max_backoff: float

    def __post_init__(self):
        # Perform validations that depend on multiple fields
        if self.stuck_active_file_timeout_seconds <= self.lost_timeout_seconds:
            raise ConfigError(
                "[Scanner] stuck_active_file_timeout_seconds must be greater than lost_timeout_seconds"
            )
        if self.max_backoff < self.initial_backoff:
            raise ConfigError("[Uploader] max_backoff must be >= initial_backoff")


# Helper functions for parsing options
def _get_string_option(
    cp: ConfigParser, section: str, option: str, allow_empty: bool = False
) -> str:
    if not cp.has_option(section, option):
        raise ConfigError(f"[{section}] missing option '{option}'")
    value = cp.get(section, option)
    if not allow_empty and not value.strip():
        raise ConfigError(f"[{section}] '{option}' cannot be empty")
    return value


def _get_int_option(
    cp: ConfigParser,
    section: str,
    option: str,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    if not cp.has_option(section, option):
        raise ConfigError(f"[{section}] missing option '{option}'")
    raw_value = cp.get(section, option)
    try:
        value = int(raw_value)
        if min_value is not None and value < min_value:
            raise ConfigError(
                f"[{section}] '{option}' ({value}) must be >= {min_value}"
            )
        if max_value is not None and value > max_value:
            raise ConfigError(
                f"[{section}] '{option}' ({value}) must be <= {max_value}"
            )
        return value
    except ValueError:
        raise ConfigError(f"[{section}] '{option}' ('{raw_value}') must be an integer")


def _get_float_option(
    cp: ConfigParser,
    section: str,
    option: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> float:
    if not cp.has_option(section, option):
        raise ConfigError(f"[{section}] missing option '{option}'")
    raw_value = cp.get(section, option)
    try:
        value = float(raw_value)
        if min_value is not None and value < min_value:
            raise ConfigError(
                f"[{section}] '{option}' ({value}) must be >= {min_value}"
            )
        if max_value is not None and value > max_value:
            raise ConfigError(
                f"[{section}] '{option}' ({value}) must be <= {max_value}"
            )
        return value
    except ValueError:
        raise ConfigError(f"[{section}] '{option}' ('{raw_value}') must be a float")


def _get_boolean_option(cp: ConfigParser, section: str, option: str) -> bool:
    if not cp.has_option(section, option):
        raise ConfigError(f"[{section}] missing option '{option}'")
    raw_value = cp.get(section, option)
    try:
        return cp.getboolean(section, option)
    except ValueError:
        raise ConfigError(
            f"[{section}] '{option}' ('{raw_value}') must be a boolean (e.g., true, false, yes, no, 1, 0)"
        )


def _parse_directories_config(
    cp: ConfigParser, fs: FS
) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    # Base directory
    base_dir_str = _get_string_option(cp, "Directories", "base_dir")
    base_expanded = Path(base_dir_str).expanduser()
    try:
        base = fs.resolve(base_expanded, strict=False)
    except OSError as e:
        raise ConfigError(f"Cannot resolve base_dir '{base_expanded}': {e}") from e
    except Exception as e:
        raise ConfigError(
            f"Unexpected error resolving base_dir '{base_expanded}': {e}"
        ) from e

    # Logger directory - must exist
    logger_dir_str = _get_string_option(cp, "Directories", "logger_dir")
    logger_dir_expanded = Path(logger_dir_str).expanduser()
    try:
        if not fs.exists(logger_dir_expanded):
            raise ConfigError(
                f"[Directories] logger_dir '{logger_dir_expanded}' does not exist."
            )
        if not fs.is_dir(logger_dir_expanded):
            raise ConfigError(
                f"[Directories] logger_dir '{logger_dir_expanded}' is not a directory."
            )
        logger_dir = fs.resolve(logger_dir_expanded, strict=True)
    except OSError as e:
        raise ConfigError(
            f"Error processing logger_dir '{logger_dir_expanded}': {e}"
        ) from e
    except Exception as e:
        raise ConfigError(
            f"Unexpected error processing logger_dir '{logger_dir_expanded}': {e}"
        ) from e

    source = base / "source"
    worker = base / "worker"
    uploaded = base / "uploaded"
    dead_letter = base / "dead_letter"
    csv_dir = base / "csv"
    return base, logger_dir, source, worker, uploaded, dead_letter, csv_dir


def _parse_files_section_config(cp: ConfigParser) -> tuple[str, str]:
    pcap_ext = _get_string_option(cp, "Files", "pcap_extension_no_dot")
    csv_ext = _get_string_option(cp, "Files", "csv_extension_no_dot")
    if not pcap_ext or "." in pcap_ext:
        raise ConfigError(
            "[Files] pcap_extension_no_dot must be a non-empty string without a dot."
        )
    if not csv_ext or "." in csv_ext:
        raise ConfigError(
            "[Files] csv_extension_no_dot must be a non-empty string without a dot."
        )
    return pcap_ext, csv_ext


def _parse_mover_config(cp: ConfigParser) -> float:
    interval = _get_float_option(
        cp, "Mover", "move_poll_interval_seconds", min_value=0.0
    )
    return interval


def _parse_scanner_config(
    cp: ConfigParser,
) -> tuple[float, float, float]:  # Return types changed to float
    scan_check_s = _get_float_option(
        cp, "Scanner", "scanner_check_seconds", min_value=1.0
    )  # Changed to float
    lost_timeout_s = _get_float_option(
        cp, "Scanner", "lost_timeout_seconds", min_value=1.0
    )  # Changed to float
    stuck_active_s = _get_float_option(
        cp, "Scanner", "stuck_active_file_timeout_seconds", min_value=1.0
    )  # Changed to float
    return scan_check_s, lost_timeout_s, stuck_active_s


def _parse_tailer_config(cp: ConfigParser) -> float:
    poll_timeout = _get_float_option(
        cp, "Tailer", "event_queue_poll_timeout_seconds", min_value=0.0
    )
    return poll_timeout


def _parse_uploader_config(
    cp: ConfigParser,
) -> tuple[
    float, float, str, float, bool, float, float
]:  # Return types changed for timeout/backoff
    uploader_poll = _get_float_option(
        cp, "Uploader", "uploader_poll_interval_seconds", min_value=0.0
    )
    heartbeat = _get_float_option(
        cp, "Uploader", "heartbeat_target_interval_s", min_value=0.0
    )
    remote_url = _get_string_option(cp, "Uploader", "remote_host_url")
    if not remote_url.startswith(("http://", "https://")):
        raise ConfigError(
            "[Uploader] remote_host_url must start with http:// or https://"
        )
    req_timeout = _get_float_option(
        cp, "Uploader", "request_timeout", min_value=1.0
    )  # Changed to float
    verify_ssl = _get_boolean_option(cp, "Uploader", "verify_ssl")
    initial_backoff = _get_float_option(
        cp, "Uploader", "initial_backoff", min_value=0.0
    )  # Changed to float
    max_backoff = _get_float_option(
        cp, "Uploader", "max_backoff", min_value=0.0
    )  # Changed to float
    return (
        uploader_poll,
        heartbeat,
        remote_url,
        req_timeout,
        verify_ssl,
        initial_backoff,
        max_backoff,
    )


def load_config(path: Union[str, Path], fs: FS = FS()) -> Config:
    """Loads, parses, and validates configuration from an INI file."""
    config_path = Path(path)
    try:
        if not fs.is_file(config_path):
            if not fs.exists(config_path):
                raise ConfigError(f"Config file not found: {config_path}")
            else:
                raise ConfigError(f"Config path is not a file: {config_path}")
    except OSError as e:
        raise ConfigError(f"Error checking config path '{config_path}': {e}") from e

    cp = ConfigParser()
    try:
        with fs.open(str(config_path), "r", encoding="utf-8") as f:
            cp.read_file(f)
    except (OSError, UnicodeDecodeError, MissingSectionHeaderError, ParsingError) as e:
        raise ConfigError(
            f"[Config] error reading or parsing config file '{config_path}': {e}"
        ) from e
    except Exception as e:
        raise ConfigError(
            f"[Config] unexpected error reading config file '{config_path}': {e}"
        ) from e

    required_sections = (
        "Directories",
        "Files",
        "Mover",
        "Scanner",
        "Tailer",
        "Uploader",
    )
    for section in required_sections:
        if not cp.has_section(section):
            raise ConfigError(f"Missing section [{section}] in '{config_path}'")

    try:
        base_d, logger_d, source_d, worker_d, uploaded_d, dead_letter_d, csv_d = (
            _parse_directories_config(cp, fs)
        )

        pcap_ext, csv_ext = _parse_files_section_config(cp)
        move_poll = _parse_mover_config(cp)
        # Types of scan_check, lost_timeout, stuck_active are now float
        scan_check, lost_timeout, stuck_active = _parse_scanner_config(cp)
        event_queue_poll = _parse_tailer_config(cp)
        # Types of req_timeout_val, initial_backoff_val, max_backoff_val are now float
        (
            uploader_poll,
            heartbeat,
            remote_url_val,
            req_timeout_val,
            verify_ssl_val,
            initial_backoff_val,
            max_backoff_val,
        ) = _parse_uploader_config(cp)

    except ConfigError:
        raise
    except NoOptionError as e:
        raise ConfigError(f"Missing option in config file '{config_path}': {e}") from e
    except Exception as e:
        raise ConfigError(
            f"Error parsing configuration sections from '{config_path}': {e}"
        ) from e

    try:
        config = Config(
            base_dir=base_d,
            logger_dir=logger_d,
            source_dir=source_d,
            worker_dir=worker_d,
            uploaded_dir=uploaded_d,
            dead_letter_dir=dead_letter_d,
            csv_dir=csv_d,
            pcap_extension_no_dot=pcap_ext,
            csv_extension_no_dot=csv_ext,
            move_poll_interval_seconds=move_poll,
            scanner_check_seconds=scan_check,
            lost_timeout_seconds=lost_timeout,
            stuck_active_file_timeout_seconds=stuck_active,
            event_queue_poll_timeout_seconds=event_queue_poll,
            uploader_poll_interval_seconds=uploader_poll,
            heartbeat_target_interval_s=heartbeat,
            remote_host_url=remote_url_val,
            request_timeout=req_timeout_val,
            verify_ssl=verify_ssl_val,
            initial_backoff=initial_backoff_val,
            max_backoff=max_backoff_val,
        )
    except ConfigError:  # Catches errors from __post_init__
        raise
    except Exception as e:
        raise ConfigError(f"Unexpected error creating Config object: {e}") from e

    return config
