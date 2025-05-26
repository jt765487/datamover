import sys

import pytest

from datamover.startup_code.cli import parse_args


def test_parse_args_defaults(monkeypatch: pytest.MonkeyPatch):
    """
    Test that parse_args returns the correct default values when no
    command-line arguments are provided (beyond the program name).
    """
    # Arrange: Simulate running the script with no arguments
    monkeypatch.setattr(sys, "argv", ["program_name.py"])

    # Act
    args = parse_args()

    # Assert: Check for default values
    assert args.dev is False, "Default for --dev should be False"
    assert args.config == "config.ini", "Default for --config should be 'config.ini'"


def test_parse_args_with_dev_flag(monkeypatch: pytest.MonkeyPatch):
    """
    Test that the --dev flag correctly sets the 'dev' attribute to True.
    """
    # Arrange: Simulate running with --dev flag
    monkeypatch.setattr(sys, "argv", ["program_name.py", "--dev"])

    # Act
    args = parse_args()

    # Assert: Check that dev is True and config is default
    assert args.dev is True, "--dev flag should set dev to True"
    assert args.config == "config.ini", "--config should remain default"


def test_parse_args_with_custom_config_long_flag(monkeypatch: pytest.MonkeyPatch):
    """
    Test that providing a custom config path using the long --config flag
    correctly sets the 'config' attribute.
    """
    # Arrange: Simulate running with --config and a custom path
    custom_config_path = "custom_path/my_settings.ini"
    monkeypatch.setattr(
        sys, "argv", ["program_name.py", "--config", custom_config_path]
    )

    # Act
    args = parse_args()

    # Assert: Check that config is the custom path and dev is default
    assert args.dev is False, "--dev should remain default"
    assert args.config == custom_config_path, (
        f"--config should be '{custom_config_path}'"
    )


def test_parse_args_with_custom_config_short_flag(monkeypatch: pytest.MonkeyPatch):
    """
    Test that providing a custom config path using the short -c flag
    correctly sets the 'config' attribute.
    """
    # Arrange: Simulate running with -c and a custom path
    custom_config_path = "another/path/settings.ini"
    monkeypatch.setattr(sys, "argv", ["program_name.py", "-c", custom_config_path])

    # Act
    args = parse_args()

    # Assert: Check that config is the custom path and dev is default
    assert args.dev is False, "--dev should remain default"
    assert args.config == custom_config_path, (
        f"-c should set config to '{custom_config_path}'"
    )


def test_parse_args_with_all_flags_set(monkeypatch: pytest.MonkeyPatch):
    """
    Test that providing both --dev and a custom config path sets all
    attributes correctly.
    """
    # Arrange: Simulate running with --dev and a custom config path
    custom_config_path = "specific/prod.ini"
    monkeypatch.setattr(
        sys, "argv", ["program_name.py", "--dev", "--config", custom_config_path]
    )

    # Act
    args = parse_args()

    # Assert: Check all attributes
    assert args.dev is True, "--dev flag should set dev to True"
    assert args.config == custom_config_path, (
        f"--config should be '{custom_config_path}'"
    )


# Optional: Test help message (more involved, tests argparse behavior)
def test_parse_args_help_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """
    Test that the help message can be invoked and contains expected argument info.
    This tests argparse's own functionality to some extent.
    """
    # Arrange: Simulate running with --help
    monkeypatch.setattr(sys, "argv", ["program_name.py", "--help"])

    # Act & Assert: argparse exits with 0 on --help
    with pytest.raises(SystemExit) as excinfo:
        parse_args()
    assert excinfo.value.code == 0

    # Assert that help message contains descriptions of arguments
    captured = capsys.readouterr()
    assert "PCAP Uploader Service" in captured.out  # Check description
    assert "--dev" in captured.out
    assert "Enable debug logging" in captured.out
    assert "--config" in captured.out
    assert "-c" in captured.out
    assert "Path to the INI configuration file" in captured.out


# Optional: Test unknown argument
def test_parse_args_unknown_argument(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """
    Test that argparse handles unknown arguments by exiting and printing an error.
    """
    # Arrange: Simulate running with an unknown argument
    unknown_arg = "--nonexistent-option"
    monkeypatch.setattr(sys, "argv", ["program_name.py", unknown_arg])

    # Act & Assert: argparse exits with non-zero code for errors
    with pytest.raises(SystemExit) as excinfo:
        parse_args()
    assert excinfo.value.code != 0  # Should be an error code (typically 2)

    # Assert that the error message contains info about the unrecognized argument
    captured = capsys.readouterr()
    assert (
        "unrecognized arguments: " + unknown_arg in captured.err.lower()
        or "unrecognised arguments: " + unknown_arg in captured.err.lower()
    )  # For different argparse versions/locales
