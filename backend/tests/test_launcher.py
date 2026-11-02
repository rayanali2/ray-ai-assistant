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
