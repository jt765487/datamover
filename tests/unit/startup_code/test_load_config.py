from pathlib import Path
from unittest.mock import MagicMock

import pytest

from datamover.file_functions.fs_mock import FS
from datamover.startup_code.load_config import load_config, ConfigError

# A minimal valid INI to start from
VALID_INI = """
[Directories]
base_dir = /tmp/base
logger_dir = /tmp/logs

[Files]
pcap_extension_no_dot = pcap
csv_extension_no_dot = csv

[Mover]
move_poll_interval_seconds = 1.5

[Scanner]
scaner_check_seconds = 2.0
lost_timeout_seconds = 3.0
stuck_active_file_timeout_seconds = 4.0

[Tailer]
event_queue_poll_timeout_seconds = 0.5

[Uploader]
uploader_poll_interval_seconds = 1.0
heartbeat_target_interval_s = 1.0
remote_host_url = http://example.com
request_timeout = 5.0
verify_ssl = true
initial_backoff = 0.1
max_backoff = 1.0
""".lstrip()


def make_fs_stub():
    """
    Returns a stub FS-like object (MagicMock) with:
      - is_file, exists, is_dir => True
      - resolve(p, strict=False|True) => Path(p)
      - open(...) => built-in open
    """
    fs = MagicMock(spec=FS)
    fs.is_file.return_value = True
    fs.exists.return_value = True
    fs.is_dir.return_value = True
    fs.resolve.side_effect = lambda p, strict=False: Path(p)
    fs.open.side_effect = lambda path, mode, encoding=None: open(
        path, mode, encoding=encoding
    )
    return fs


@pytest.fixture(autouse=True)
def ensure_logger_dir(tmp_path):
    """
    Ensure that /tmp/logs exists on disk for VALID_INI's logger_dir.
    """
    logs = Path("/tmp/logs")
    logs.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def config_file(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text(VALID_INI)
    return cfg


def test_load_config_happy_path(config_file):
    fs = make_fs_stub()
    cfg = load_config(str(config_file), fs=fs)

    # Directories
    assert cfg.base_dir == Path("/tmp/base")
    assert cfg.logger_dir == Path("/tmp/logs")
    assert cfg.source_dir == Path("/tmp/base") / "source"
    assert cfg.worker_dir == Path("/tmp/base") / "worker"
    assert cfg.uploaded_dir == Path("/tmp/base") / "uploaded"
    assert cfg.dead_letter_dir == Path("/tmp/base") / "dead_letter"
    assert cfg.csv_dir == Path("/tmp/base") / "csv"

    # Files
    assert cfg.pcap_extension_no_dot == "pcap"
    assert cfg.csv_extension_no_dot == "csv"

    # Mover
    assert cfg.move_poll_interval_seconds == 1.5

    # Scanner
    assert cfg.scanner_check_seconds == 2.0
    assert cfg.lost_timeout_seconds == 3.0
    assert cfg.stuck_active_file_timeout_seconds == 4.0

    # Tailer
    assert cfg.event_queue_poll_timeout_seconds == 0.5

    # Uploader
    assert cfg.uploader_poll_interval_seconds == 1.0
    assert cfg.heartbeat_target_interval_s == 1.0
    assert cfg.remote_host_url == "http://example.com"
    assert cfg.request_timeout == 5.0
    assert cfg.verify_ssl is True
    assert cfg.initial_backoff == 0.1
    assert cfg.max_backoff == 1.0


def test_config_file_not_found(tmp_path):
    fs = make_fs_stub()
    fs.is_file.return_value = False
    fs.exists.return_value = False

    with pytest.raises(ConfigError) as exc:
        load_config(str(tmp_path / "nope.ini"), fs=fs)
    assert "Config file not found" in str(exc.value)


def test_config_path_not_a_file(tmp_path):
    fs = make_fs_stub()
    fs.is_file.return_value = False
    fs.exists.return_value = True

    with pytest.raises(ConfigError) as exc:
        load_config(str(tmp_path / "weird"), fs=fs)
    assert "Config path is not a file" in str(exc.value)


@pytest.mark.parametrize(
    "section,key",
    [
        ("Directories", "base_dir"),
        ("Directories", "logger_dir"),
        ("Files", "pcap_extension_no_dot"),
        ("Files", "csv_extension_no_dot"),
        ("Mover", "move_poll_interval_seconds"),
        ("Scanner", "scaner_check_seconds"),
        ("Scanner", "lost_timeout_seconds"),
        ("Scanner", "stuck_active_file_timeout_seconds"),
        ("Tailer", "event_queue_poll_timeout_seconds"),
        ("Uploader", "uploader_poll_interval_seconds"),
        ("Uploader", "heartbeat_target_interval_s"),
        ("Uploader", "remote_host_url"),
        ("Uploader", "request_timeout"),
        ("Uploader", "verify_ssl"),
        ("Uploader", "initial_backoff"),
        ("Uploader", "max_backoff"),
    ],
)
def test_missing_option_raises(section, key, tmp_path):
    txt = VALID_INI.replace(f"{key} =", f";{key} =")
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert f"[{section}] missing option '{key}'" in str(exc.value)


def test_missing_section_raises(tmp_path):
    txt = VALID_INI.replace("[Scanner]", "[Scanns]")
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "Missing section [Scanner]" in str(exc.value)


def test_bad_float_parsing(tmp_path):
    txt = VALID_INI.replace(
        "move_poll_interval_seconds = 1.5", "move_poll_interval_seconds = notafloat"
    )
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "must be a float" in str(exc.value)


def test_bad_boolean(tmp_path):
    txt = VALID_INI.replace("verify_ssl = true", "verify_ssl = maybe")
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "must be a boolean" in str(exc.value)


def test_invalid_remote_url(tmp_path):
    txt = VALID_INI.replace(
        "remote_host_url = http://example.com", "remote_host_url = ftp://example.com"
    )
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "remote_host_url must start with" in str(exc.value)


def test_logger_dir_checks(tmp_path):
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(VALID_INI)
    fs = make_fs_stub()

    fs.exists.return_value = False  # logger_dir does not exist
    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "logger_dir '/tmp/logs' does not exist" in str(exc.value)

    fs.exists.return_value = True
    fs.is_dir.return_value = False  # not a dir
    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "logger_dir '/tmp/logs' is not a directory" in str(exc.value)


def test_base_dir_resolve_os_error(tmp_path):
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(VALID_INI)
    fs = make_fs_stub()
    fs.resolve.side_effect = OSError("boom")

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "Cannot resolve base_dir" in str(exc.value)


def test_scanner_timeouts_validation(tmp_path):
    txt = VALID_INI.replace("lost_timeout_seconds = 3.0", "lost_timeout_seconds = 5.0")
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(txt)
    fs = make_fs_stub()

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "stuck_active_file_timeout_seconds must be greater" in str(exc.value)


def test_uploader_backoff_validation(tmp_path):
    lines = VALID_INI.splitlines()
    output_lines = []
    for line in lines:
        if line.strip().startswith("initial_backoff ="):
            output_lines.append("initial_backoff = 2.0")
        elif line.strip().startswith("max_backoff ="):
            output_lines.append(
                "max_backoff = 1.0"
            )  # This makes initial (2.0) > max (1.0)
        else:
            output_lines.append(line)
    txt = "\n".join(output_lines)

    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(txt)
    fs = make_fs_stub()

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "max_backoff must be >= initial_backoff" in str(exc.value)
