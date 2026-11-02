import os
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "scripts/install.sh"


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\nset -eu\n" + body)
    path.chmod(0o755)


@pytest.mark.parametrize("tools", ["missing", "old-node", "ready"])
def test_installer_bootstraps_and_reuses_tools(tmp_path, tools):
    home = tmp_path / "home"
    home.mkdir()
    checkout = home / "ray-ai-assistant"
    executable(checkout / "scripts/ray", "exit 0\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "docker", "exit 0\n")
    executable(bin_dir / "git", 'echo git >> "$HOME/calls"\n')
    executable(
        bin_dir / "curl",
        """
case "$*" in
  *astral*) cat <<'INSTALL'
mkdir -p "$UV_INSTALL_DIR"
printf '#!/bin/bash\necho "uv $*" >> "$HOME/calls"\n' > "$UV_INSTALL_DIR/uv"
chmod +x "$UV_INSTALL_DIR/uv"
INSTALL
;;
  *pnpm*) cat <<'INSTALL'
mkdir -p "$PNPM_HOME"
printf '#!/bin/bash\necho "pnpm $*" >> "$HOME/calls"\n' > "$PNPM_HOME/pnpm"
chmod +x "$PNPM_HOME/pnpm"
INSTALL
;;
esac
""",
    )
    if tools != "missing":
        executable(bin_dir / "uv", 'echo "uv $*" >> "$HOME/calls"\n')
        executable(bin_dir / "pnpm", 'echo "pnpm $*" >> "$HOME/calls"\n')
    executable(bin_dir / "node", "exit " + ("0" if tools == "ready" else "1") + "\n")
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "PNPM_HOME": str(home / "pnpm"),
        "RAY_FROM_DESKTOP": "1",
    }
    env.pop("RAY_GEMINI_API_KEY", None)
    installer = tmp_path / "install.sh"
    installer.write_text(INSTALLER.read_text())
    result = subprocess.run(
        ["/bin/bash", str(installer)], cwd=home, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    calls = (home / "calls").read_text()
    assert "init --preset auto" in calls
    assert "start --no-browser" in calls
    assert "clone" not in calls
    assert ("pnpm env use --global 22" in calls) == (tools != "ready")
    assert (home / ".local/bin/uv").exists() == (tools == "missing")


def test_mac_missing_git_requests_command_line_tools_before_clone(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "uname", "echo Darwin\n")
    executable(bin_dir / "git", "exit 1\n")
    executable(bin_dir / "xcode-select", 'echo "Command Line Tools requested"\n')
    result = subprocess.run(
        ["/bin/bash", str(INSTALLER)],
        cwd=tmp_path,
        env={**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Command Line Tools requested" in result.stdout
    assert "click Install Ray again" in result.stderr
    assert not (tmp_path / "ray-ai-assistant").exists()


def test_mac_missing_docker_opens_download_and_exits(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("curl", "git", "python3"):
        executable(bin_dir / name, "exit 0\n")
    executable(bin_dir / "uname", "echo Darwin\n")
    executable(bin_dir / "open", 'echo "Opening $*"\n')
    result = subprocess.run(
        ["/bin/bash", str(INSTALLER)],
        cwd=tmp_path,
        env={**os.environ, "HOME": str(tmp_path), "PATH": str(bin_dir)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Opening https://www.docker.com/products/docker-desktop/" in result.stdout
    assert "Install Docker Desktop, open it once" in result.stderr
