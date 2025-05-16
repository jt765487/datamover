from pathlib import Path
from unittest.mock import MagicMock, patch
from configparser import MissingSectionHeaderError, ParsingError, ConfigParser
import pytest

from datamover.file_functions.fs_mock import FS
from datamover.startup_code.load_config import load_config, ConfigError

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
      - is_file, exists, is_dir => True by default
      - resolve(p, strict=False|True) => Path(p)
      - open(...) => built-in open
    """
    fs = MagicMock(spec=FS)
    fs.is_file.return_value = True
    fs.exists.return_value = True
    fs.is_dir.return_value = True

    def resolve_side_effect(p, strict=False):
        path_obj = Path(p).expanduser()  # Ensure expanduser is also called in mock
        # Simulate strict check more accurately
        # In a real fs.resolve(strict=True), if the path doesn't exist, FileNotFoundError is raised.
        # If strict=False, it can return a path that doesn't exist yet.
        if strict and not fs.exists(path_obj):  # fs.exists is also mockable per test
            raise FileNotFoundError(
                f"Mock FileNotFoundError for {path_obj} (strict=True)"
            )
        return path_obj

    fs.resolve.side_effect = resolve_side_effect

    # Make fs.open also mockable but default to real open for simplicity in most tests
    # We use a real open so that config_file.write_text works, and then load_config reads it.
    # For specific open errors, we mock fs.open.side_effect in that test.
    fs.open.side_effect = lambda path, mode, encoding=None: open(
        path, mode, encoding=encoding
    )
    return fs


@pytest.fixture(autouse=True)
def ensure_logger_dir_default(tmp_path):
    """
    Ensure that the default logger_dir from VALID_INI exists.
    Tests needing specific fs.exists behavior for logger_dir can override fs.exists.
    """
    # This path is hardcoded in VALID_INI. If VALID_INI changes, this might need to.
    default_logger_path = Path("/tmp/logs")
    if (
        not default_logger_path.exists()
    ):  # Only create if it doesn't exist on test runner
        default_logger_path.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def config_file(tmp_path):
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(VALID_INI)
    return cfg_path


def test_load_config_happy_path(config_file):
    fs = make_fs_stub()
    # For happy path, ensure logger_dir "exists" for the mock resolve(strict=True)
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/logs").expanduser()
        or p == Path("/tmp/base").expanduser()
    )

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
    fs.exists.return_value = False  # Crucial for this test case

    with pytest.raises(ConfigError) as exc:
        load_config(str(tmp_path / "nope.ini"), fs=fs)
    assert "Config file not found" in str(exc.value)


def test_config_path_not_a_file(tmp_path):
    fs = make_fs_stub()
    fs.is_file.return_value = False
    fs.exists.return_value = True  # It exists but is not a file

    with pytest.raises(ConfigError) as exc:
        load_config(str(tmp_path / "weird_dir"), fs=fs)
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
def test_missing_option_raises(
    section, key, tmp_path, config_file
):  # Added config_file to make replacement easier
    original_content = config_file.read_text()
    # More robust replacement: comment out the specific line
    lines = original_content.splitlines()
    modified_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key} ="):
            modified_lines.append(f";{line}")  # Comment it out
            found = True
        else:
            modified_lines.append(line)
    assert found, f"Key {key} not found in VALID_INI for commenting."
    txt = "\n".join(modified_lines)

    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/logs").expanduser()
        or p == Path("/tmp/base").expanduser()
        or p == cfg_path
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert f"[{section}] missing option '{key}'" in str(exc.value)


def test_missing_section_raises(tmp_path, config_file):
    txt = config_file.read_text().replace("[Scanner]", "[Scanns]")  # Intentional typo
    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/logs").expanduser()
        or p == Path("/tmp/base").expanduser()
        or p == cfg_path
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "Missing section [Scanner]" in str(exc.value)


def test_bad_float_parsing(tmp_path, config_file):
    txt = config_file.read_text().replace(
        "move_poll_interval_seconds = 1.5", "move_poll_interval_seconds = notafloat"
    )
    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/logs").expanduser()
        or p == Path("/tmp/base").expanduser()
        or p == cfg_path
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "must be a float" in str(exc.value)
    assert "[Mover] 'move_poll_interval_seconds' ('notafloat')" in str(exc.value)


def test_bad_boolean(tmp_path, config_file):
    txt = config_file.read_text().replace("verify_ssl = true", "verify_ssl = maybe")
    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/logs").expanduser()
        or p == Path("/tmp/base").expanduser()
        or p == cfg_path
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "must be a boolean" in str(exc.value)
    assert "[Uploader] 'verify_ssl' ('maybe')" in str(exc.value)


def test_invalid_remote_url(tmp_path, config_file):
    txt = config_file.read_text().replace(
        "remote_host_url = http://example.com", "remote_host_url = ftp://example.com"
    )
    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/logs").expanduser()
        or p == Path("/tmp/base").expanduser()
        or p == cfg_path
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "remote_host_url must start with http:// or https://" in str(exc.value)


def test_logger_dir_checks(config_file, tmp_path):  # tmp_path is used by config_file
    fs = make_fs_stub()
    # Ensure base_dir related checks pass for this test
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/base").expanduser() or p == config_file
    )

    # Scenario 1: logger_dir does not exist
    mock_logger_path = Path("/tmp/non_existent_logs").expanduser()
    modified_ini = config_file.read_text().replace(
        "logger_dir = /tmp/logs", f"logger_dir = {mock_logger_path}"
    )
    cfg_path_scenario1 = tmp_path / "s1_config.ini"
    cfg_path_scenario1.write_text(modified_ini)

    fs_s1 = make_fs_stub()
    fs_s1.exists.side_effect = (
        lambda p: p == Path("/tmp/base").expanduser()
        or p == cfg_path_scenario1
        or (p == mock_logger_path and False)
    )  # logger_dir doesn't exist
    fs_s1.is_file.side_effect = lambda p: p == cfg_path_scenario1  # config is a file

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path_scenario1), fs=fs_s1)
    assert f"logger_dir '{mock_logger_path}' does not exist" in str(exc.value)

    # Scenario 2: logger_dir exists but is not a directory
    mock_logger_file_path = Path("/tmp/logger_is_a_file").expanduser()
    modified_ini_s2 = config_file.read_text().replace(
        "logger_dir = /tmp/logs", f"logger_dir = {mock_logger_file_path}"
    )
    cfg_path_scenario2 = tmp_path / "s2_config.ini"
    cfg_path_scenario2.write_text(modified_ini_s2)

    fs_s2 = make_fs_stub()
    fs_s2.exists.side_effect = (
        lambda p: p == Path("/tmp/base").expanduser()
        or p == cfg_path_scenario2
        or p == mock_logger_file_path
    )  # logger_path "exists"
    fs_s2.is_dir.side_effect = (
        lambda p: p != mock_logger_file_path
    )  # logger_path is NOT a dir
    fs_s2.is_file.side_effect = (
        lambda p: p == cfg_path_scenario2 or p == mock_logger_file_path
    )  # config is a file, logger path is a file

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path_scenario2), fs=fs_s2)
    assert f"logger_dir '{mock_logger_file_path}' is not a directory" in str(exc.value)


def test_base_dir_resolve_os_error(config_file):
    fs = make_fs_stub()
    fs.resolve.side_effect = OSError("boom resolve base_dir")  # Global resolve error

    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file), fs=fs)
    assert "Cannot resolve base_dir" in str(exc.value)
    assert "boom resolve base_dir" in str(exc.value)


def test_scanner_timeouts_validation(tmp_path, config_file):
    txt = config_file.read_text().replace(
        "lost_timeout_seconds = 3.0", "lost_timeout_seconds = 5.0"
    )  # 5.0 > 4.0
    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(txt)

    fs = make_fs_stub()
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/logs").expanduser()
        or p == Path("/tmp/base").expanduser()
        or p == cfg_path
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "stuck_active_file_timeout_seconds must be greater" in str(exc.value)


def test_uploader_backoff_validation(tmp_path, config_file):
    original_content = config_file.read_text()
    lines = original_content.splitlines()
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

    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(txt)
    fs = make_fs_stub()
    fs.exists.side_effect = (
        lambda p: p == Path("/tmp/logs").expanduser()
        or p == Path("/tmp/base").expanduser()
        or p == cfg_path
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "max_backoff must be >= initial_backoff" in str(exc.value)


# --- New Tests ---


@pytest.mark.parametrize(
    "key_to_modify,bad_value,expected_error_msg_part",
    [
        ("pcap_extension_no_dot", "", f"'{'pcap_extension_no_dot'}' cannot be empty"),
        (
            "pcap_extension_no_dot",
            ".pcap",
            "pcap_extension_no_dot must be a non-empty string without a dot",
        ),
        ("csv_extension_no_dot", "", f"'{'csv_extension_no_dot'}' cannot be empty"),
        (
            "csv_extension_no_dot",
            ".csv",
            "csv_extension_no_dot must be a non-empty string without a dot",
        ),
    ],
)
def test_bad_file_extensions(
    tmp_path, key_to_modify, bad_value, expected_error_msg_part, config_file
):
    original_content = config_file.read_text()
    # Robustly find and replace the specific line
    lines = original_content.splitlines()
    modified_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key_to_modify} ="):
            modified_lines.append(f"{key_to_modify} = {bad_value}")
            found = True
        else:
            modified_lines.append(line)
    assert found, f"Key {key_to_modify} not found in VALID_INI for replacement."
    modified_ini = "\n".join(modified_lines)

    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(modified_ini)
    fs = make_fs_stub()
    # Make sure default logger and base dirs "exist" for the mock FS
    fs.exists.side_effect = lambda p: p in (
        Path("/tmp/logs").expanduser(),
        Path("/tmp/base").expanduser(),
        cfg_path,
    )
    fs.is_file.side_effect = lambda p: p == cfg_path  # Only config path is a file

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)

    assert expected_error_msg_part in str(exc.value)
    if bad_value == "":  # Check section for this specific error from _get_string_option
        assert "[Files]" in str(exc.value)


@pytest.mark.parametrize(
    "section,key,bad_value,min_value_text_for_msg",  # min_value_text_for_msg used for error string
    [
        ("Mover", "move_poll_interval_seconds", "-1.0", "0.0"),
        ("Scanner", "scaner_check_seconds", "0.5", "1.0"),
        ("Scanner", "lost_timeout_seconds", "0", "1.0"),
        ("Scanner", "stuck_active_file_timeout_seconds", "-5", "1.0"),
        ("Tailer", "event_queue_poll_timeout_seconds", "-0.1", "0.0"),
        ("Uploader", "uploader_poll_interval_seconds", "-1", "0.0"),
        ("Uploader", "heartbeat_target_interval_s", "-60.0", "0.0"),
        ("Uploader", "request_timeout", "0.5", "1.0"),
        ("Uploader", "initial_backoff", "-0.1", "0.0"),
        ("Uploader", "max_backoff", "-1", "0.0"),
    ],
)
def test_numeric_value_below_min(
    tmp_path, section, key, bad_value, min_value_text_for_msg, config_file
):
    original_content = config_file.read_text()
    lines = original_content.splitlines()
    modified_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key} ="):
            modified_lines.append(f"{key} = {bad_value}")
            found = True
        else:
            modified_lines.append(line)
    assert found, f"Key {key} not found in VALID_INI for replacement."
    modified_ini = "\n".join(modified_lines)

    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(modified_ini)
    fs = make_fs_stub()
    fs.exists.side_effect = lambda p: p in (
        Path("/tmp/logs").expanduser(),
        Path("/tmp/base").expanduser(),
        cfg_path,
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert f"must be >= {min_value_text_for_msg}" in str(exc.value)
    assert f"[{section}] '{key}'" in str(exc.value)


def test_empty_remote_host_url(tmp_path, config_file):
    modified_ini = config_file.read_text().replace(
        "remote_host_url = http://example.com", "remote_host_url = "
    )
    cfg_path = tmp_path / "config_modified.ini"
    cfg_path.write_text(modified_ini)
    fs = make_fs_stub()
    fs.exists.side_effect = lambda p: p in (
        Path("/tmp/logs").expanduser(),
        Path("/tmp/base").expanduser(),
        cfg_path,
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "[Uploader] 'remote_host_url' cannot be empty" in str(exc.value)


def test_load_config_os_error_on_initial_path_check(tmp_path):
    fs = make_fs_stub()
    fs.is_file.side_effect = OSError("Disk read error during is_file")
    config_path_str = str(tmp_path / "config.ini")  # This file won't be written

    with pytest.raises(ConfigError) as exc:
        load_config(config_path_str, fs=fs)
    assert "Error checking config path" in str(exc.value)
    assert "Disk read error during is_file" in str(exc.value)


def test_load_config_unicode_decode_error(tmp_path):
    config_path = tmp_path / "config.ini"
    config_path.write_bytes(
        b"\xff\xfe[Directories]\nbase_dir = /tmp/base\n"
    )  # Invalid UTF-8 start
    fs = make_fs_stub()
    # Ensure fs.is_file and fs.exists pass for config_path
    fs.is_file.side_effect = lambda p: p == config_path
    fs.exists.side_effect = lambda p: p == config_path

    with pytest.raises(ConfigError) as exc:
        load_config(str(config_path), fs=fs)
    assert "error reading or parsing config file" in str(exc.value)
    assert "codec can't decode byte" in str(exc.value)


@pytest.mark.parametrize(
    "malformed_ini_content, expected_exception_type",
    [
        ("NoSectionHeader\nkey = value", MissingSectionHeaderError),
        ("[Section]\nkey_no_value", ParsingError),
        ("[Section]\n: value_no_key", ParsingError),
    ],
)
def test_load_config_malformed_ini(
    tmp_path, malformed_ini_content, expected_exception_type
):
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(malformed_ini_content)
    fs = make_fs_stub()
    fs.is_file.side_effect = lambda p: p == cfg_path
    fs.exists.side_effect = lambda p: p == cfg_path

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "error reading or parsing config file" in str(exc.value)
    assert isinstance(exc.value.__cause__, expected_exception_type)


def test_logger_dir_resolve_os_error(tmp_path, config_file):
    fs = make_fs_stub()
    # Ensure initial checks for logger_dir pass and base_dir resolves
    default_logger_path = Path("/tmp/logs").expanduser()
    default_base_path = Path("/tmp/base").expanduser()

    def selective_exists(p):
        return p in (default_logger_path, default_base_path, config_file)

    fs.exists.side_effect = selective_exists
    fs.is_dir.side_effect = lambda p: p in (default_logger_path, default_base_path)

    _original_resolve = fs.resolve.side_effect

    def custom_resolve(p, strict=False):
        expanded_p = Path(p).expanduser()
        if (
            expanded_p == default_logger_path and strict
        ):  # Error only for logger_dir's strict resolve
            raise OSError("boom on logger_dir strict resolve")
        # For base_dir and other non-strict resolves, or non-logger strict resolves
        if strict and not fs.exists(expanded_p):
            raise FileNotFoundError(
                f"Mock FileNotFoundError for {expanded_p} (strict=True)"
            )
        return expanded_p

    fs.resolve.side_effect = custom_resolve

    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file), fs=fs)
    assert "Error processing logger_dir '/tmp/logs'" in str(exc.value)
    assert "boom on logger_dir strict resolve" in str(exc.value)


def test_base_dir_resolve_unexpected_error(config_file):
    fs = make_fs_stub()
    # Let logger_dir resolve fine
    fs.exists.side_effect = lambda p: p in (Path("/tmp/logs").expanduser(), config_file)

    def custom_resolve_base(p, strict=False):
        expanded_p = Path(p).expanduser()
        if (
            expanded_p == Path("/tmp/base").expanduser() and not strict
        ):  # Error for base_dir (non-strict)
            raise ValueError("Unexpected base_dir resolve error")
        if strict and not fs.exists(expanded_p):
            raise FileNotFoundError(
                f"Mock FileNotFoundError for {expanded_p} (strict=True)"
            )
        return expanded_p  # For logger_dir

    fs.resolve.side_effect = custom_resolve_base

    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file), fs=fs)
    assert "Unexpected error resolving base_dir" in str(exc.value)
    assert "Unexpected base_dir resolve error" in str(exc.value)


def test_logger_dir_resolve_unexpected_error(config_file):
    fs = make_fs_stub()
    default_logger_path = Path("/tmp/logs").expanduser()
    default_base_path = Path("/tmp/base").expanduser()

    fs.exists.side_effect = lambda p: p in (
        default_logger_path,
        default_base_path,
        config_file,
    )
    fs.is_dir.side_effect = lambda p: p in (default_logger_path, default_base_path)

    def custom_resolve_logger(p, strict=False):
        expanded_p = Path(p).expanduser()
        if expanded_p == default_logger_path and strict:
            raise ValueError("Unexpected logger resolve error")
        if strict and not fs.exists(expanded_p):
            raise FileNotFoundError(
                f"Mock FileNotFoundError for {expanded_p} (strict=True)"
            )
        return expanded_p

    fs.resolve.side_effect = custom_resolve_logger

    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file), fs=fs)
    assert "Unexpected error processing logger_dir" in str(exc.value)
    assert "Unexpected logger resolve error" in str(exc.value)


def test_unexpected_error_in_config_parser_open(tmp_path):
    cfg_path = tmp_path / "config.ini"  # File doesn't need to exist if open is mocked
    fs = make_fs_stub()
    fs.is_file.return_value = True  # Assume it's a file to get to fs.open
    fs.exists.return_value = True
    fs.open.side_effect = RuntimeError("Custom fs.open failure")

    with pytest.raises(ConfigError) as exc:
        load_config(str(cfg_path), fs=fs)
    assert "unexpected error reading config file" in str(exc.value)
    assert "Custom fs.open failure" in str(exc.value)


def test_unexpected_error_during_section_parsing(config_file):
    fs = make_fs_stub()
    fs.exists.side_effect = lambda p: p in (
        Path("/tmp/logs").expanduser(),
        Path("/tmp/base").expanduser(),
        config_file,
    )

    with patch(
        "datamover.startup_code.load_config._parse_files_section_config",
        side_effect=ValueError("Internal parse boom"),
    ):
        with pytest.raises(ConfigError) as exc:
            load_config(str(config_file), fs=fs)
        assert "Error parsing configuration sections from" in str(exc.value)
        assert "Internal parse boom" in str(exc.value)


def test_unexpected_error_during_config_instantiation(config_file):
    fs = make_fs_stub()
    fs.exists.side_effect = lambda p: p in (
        Path("/tmp/logs").expanduser(),
        Path("/tmp/base").expanduser(),
        config_file,
    )

    with patch("datamover.startup_code.load_config.Config") as MockConfigClass:
        MockConfigClass.side_effect = TypeError("Config class init boom")
        with pytest.raises(ConfigError) as exc:
            load_config(str(config_file), fs=fs)
        assert "Unexpected error creating Config object" in str(exc.value)
        assert "Config class init boom" in str(exc.value)


# Example tests for _get_int_option (if you decide to keep/use it)
def test_get_int_option_validations():
    cp = ConfigParser()
    cp.add_section("TestInt")
    cp.set("TestInt", "good_int", "10")
    cp.set("TestInt", "bad_int_format", "notanint")
    cp.set("TestInt", "too_low", "0")
    cp.set("TestInt", "too_high", "100")
    cp.set("TestInt", "empty_val", "")

    from datamover.startup_code.load_config import _get_int_option

    assert _get_int_option(cp, "TestInt", "good_int", min_value=0, max_value=20) == 10

    with pytest.raises(ConfigError, match="must be an integer"):
        _get_int_option(cp, "TestInt", "bad_int_format")
    with pytest.raises(ConfigError, match="must be >= 5"):
        _get_int_option(cp, "TestInt", "too_low", min_value=5)
    with pytest.raises(ConfigError, match="must be <= 50"):
        _get_int_option(cp, "TestInt", "too_high", max_value=50)
    with pytest.raises(ConfigError, match="missing option 'non_existent'"):
        _get_int_option(cp, "TestInt", "non_existent")
    with pytest.raises(ConfigError, match="'empty_val' .* must be an integer"):
        _get_int_option(cp, "TestInt", "empty_val")
