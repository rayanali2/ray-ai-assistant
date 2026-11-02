import argparse
import json
import runpy
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("contents", "exported", "expected"),
    [
        ('RAY_API_TOKEN="file-token"\nRAY_API_URL=http://localhost:8000\n', None, "file-token"),
        ("RAY_API_TOKEN=file-token\n", "exported-token", "exported-token"),
        (None, "exported-token", "exported-token"),
        ("", None, None),
        ("RAY_API_TOKEN=file-token\n", "", ""),
    ],
)
def test_service_environment(tmp_path, monkeypatch, contents, exported, expected):
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "ray"))
    env_file = tmp_path / ".env"
    if contents is not None:
        env_file.write_text(contents)
    launcher["_read_env"].__globals__["ENV_FILE"] = env_file
    monkeypatch.delenv("RAY_API_TOKEN", raising=False)
    monkeypatch.setenv("RAY_LAUNCHER_INHERITED", "inherited")
    if exported is not None:
        monkeypatch.setenv("RAY_API_TOKEN", exported)

    log = tmp_path / "service.log"
    proc = launcher["_run_bg"](
        [
            sys.executable,
            "-c",
            "import json, os; print(json.dumps(dict(os.environ)))",
        ],
        tmp_path,
        log,
    )
    assert proc.wait(timeout=10) == 0
    child_env = json.loads(log.read_text())
    assert child_env.get("RAY_API_TOKEN") == expected
    assert child_env["RAY_LAUNCHER_INHERITED"] == "inherited"
    if contents and "RAY_API_URL=" in contents:
        assert child_env["RAY_API_URL"] == "http://localhost:8000"


def test_service_launch_error(tmp_path):
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "ray"))
    launcher["_read_env"].__globals__["ENV_FILE"] = tmp_path / ".env"
    with pytest.raises(FileNotFoundError):
        launcher["_run_bg"]([str(tmp_path / "missing-executable")], tmp_path, tmp_path / "log")


@pytest.mark.parametrize("has_key", [False, True])
def test_subscriptions_preset(tmp_path, monkeypatch, has_key):
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "ray"))
    launcher["_init"].__globals__["ENV_FILE"] = tmp_path / ".env"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("RAY_GEMINI_API_KEY", raising=False)
    if has_key:
        monkeypatch.setenv("RAY_GEMINI_API_KEY", "test-key")
    launcher["_init"](argparse.Namespace(preset="subscriptions", name="Test", force=False))
    env = launcher["_read_env"]()
    assert env["RAY_LLM_PROVIDER"] == ("gemini" if has_key else "claude_cli")
    assert env["RAY_LLM_FALLBACK_PROVIDER"] == "claude_cli,codex_cli,ollama"


@pytest.mark.parametrize("installed", [False, True])
def test_doctor_optional_cli_does_not_fail(tmp_path, monkeypatch, capsys, installed):
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "ray"))
    scope = launcher["_doctor"].__globals__
    scope["ENV_FILE"] = tmp_path / ".env"
    scope["ENV_FILE"].write_text(
        "RAY_API_TOKEN=test\nRAY_DATABASE_URL=test\nRAY_LLM_PROVIDER=mock\n"
    )
    scope["_service_port"] = lambda *args: True
    scope["_health"] = lambda: True
    monkeypatch.setattr(
        scope["shutil"],
        "which",
        lambda name: None if not installed and name in {"claude", "codex"} else "/fake/" + name,
    )
    monkeypatch.setattr(
        scope["subprocess"],
        "run",
        lambda *args, **kwargs: argparse.Namespace(
            returncode=1, stdout='{"loggedIn":false}', stderr=""
        ),
    )
    with pytest.raises(SystemExit) as exc:
        launcher["_doctor"](argparse.Namespace())
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Claude CLI (optional):" in output
    assert "Codex CLI (optional):" in output


@pytest.mark.parametrize(
    "key,cli,provider",
    [
        ("test-key", None, "gemini"),
        ("", "codex_cli", "codex_cli"),
        ("", "claude_cli", "claude_cli"),
        ("", None, "ollama"),
    ],
)
def test_auto_preset(tmp_path, monkeypatch, capsys, key, cli, provider):
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "ray"))
    scope = launcher["_init"].__globals__
    scope["ENV_FILE"] = tmp_path / ".env"
    scope["_logged_in_cli"] = lambda: cli
    monkeypatch.setenv("RAY_GEMINI_API_KEY", key)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    launcher["_init"](argparse.Namespace(preset="auto", name="Test", force=False))
    env = launcher["_read_env"]()
    assert env["RAY_LLM_PROVIDER"] == provider
    assert env["RAY_EMBEDDING_BACKEND"] == "hashing"
    assert env.get("RAY_GEMINI_API_KEY", "") == key
    assert scope["ENV_FILE"].stat().st_mode & 0o777 == 0o600
    assert "test-key" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "output,code,expected",
    [
        ("not logged in", 1, None),
        ("Logged in using ChatGPT", 0, "codex_cli"),
        ("invalid JSON", 0, None),
    ],
)
def test_auto_cli_requires_login(monkeypatch, output, code, expected):
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "ray"))
    monkeypatch.setattr(launcher["shutil"], "which", lambda name: name)
    monkeypatch.setattr(
        launcher["subprocess"],
        "run",
        lambda *a, **kw: argparse.Namespace(returncode=code, stdout=output, stderr=""),
    )
    assert launcher["_logged_in_cli"]() == expected


@pytest.mark.parametrize("key", ["", "bad\nRAY_API_TOKEN=injected", '"quoted"'])
def test_key_configuration_rejects_empty_or_unsafe_input(tmp_path, monkeypatch, key):
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "ray"))
    scope = launcher["_configure_key"].__globals__
    scope["ENV_FILE"] = tmp_path / ".env"
    scope["ENV_FILE"].write_text("RAY_API_TOKEN=keep\n")
    monkeypatch.setenv("RAY_GEMINI_API_KEY", key)
    with pytest.raises(SystemExit):
        launcher["_configure_key"](argparse.Namespace())
    assert scope["ENV_FILE"].read_text() == "RAY_API_TOKEN=keep\n"


def test_change_key_preserves_configuration(tmp_path, monkeypatch, capsys):
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "ray"))
    scope = launcher["_configure_key"].__globals__
    scope["ENV_FILE"] = tmp_path / ".env"
    scope["ENV_FILE"].write_text("RAY_API_TOKEN=keep\nRAY_USER_NAME=Test\n")
    monkeypatch.setenv("RAY_GEMINI_API_KEY", "test-key")
    launcher["_configure_key"](argparse.Namespace())
    env = launcher["_read_env"]()
    assert env["RAY_API_TOKEN"] == "keep"
    assert env["RAY_USER_NAME"] == "Test"
    assert env["RAY_GEMINI_API_KEY"] == "test-key"
    assert env["RAY_LLM_PROVIDER"] == "gemini"
    assert "test-key" not in capsys.readouterr().out
