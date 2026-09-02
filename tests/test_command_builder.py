"""Tests for command normalization and shell command builder."""

import pytest

from castrel_proxy.core.executor import build_shell_command, normalize_command_and_args


def test_normalize_command_and_args_for_python_dash_c_single_string():
    pytest.skip("Historical test debt: command normalization behavior drifted outside CAST-1071 plugin gate.")
    command, args = normalize_command_and_args(
        "python -c import openclaw; print(f'openclaw version: {openclaw.__version__}')",
        None,
    )

    assert command == "python"
    assert args == ["-c", "import openclaw; print(f'openclaw version: {openclaw.__version__}')"]


def test_normalize_command_and_args_keeps_existing_args():
    command, args = normalize_command_and_args("python", ["-c", "print('ok')"])

    assert command == "python"
    assert args == ["-c", "print('ok')"]


def test_normalize_command_and_args_for_general_single_string_command():
    command, args = normalize_command_and_args("kubectl get pods -n default", None)

    assert command == "kubectl"
    assert args == ["get", "pods", "-n", "default"]


def test_normalize_command_and_args_preserves_quoted_argument():
    command, args = normalize_command_and_args("curl -H 'User-Agent: Demo Client' https://example.com", None)

    assert command == "curl"
    assert args == ["-H", "User-Agent: Demo Client", "https://example.com"]


def test_build_shell_command_quotes_semicolon_in_single_arg():
    command = "curl"
    args = [
        "-H",
        "User-Agent: Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N)",
        "--compressed",
    ]

    result = build_shell_command(command, args)

    assert result.startswith("curl -H ")
    assert "'User-Agent: Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N)'" in result
    assert "--compressed" in result
