# One-liner install for Ray on Windows.
#
#   irm https://raw.githubusercontent.com/rayanali2/ray-ai-assistant/main/scripts/install.ps1 | iex
#
# Or, from a local clone:
#
#   .\scripts\install.ps1
#
# The script checks for the required tooling, then runs `scripts\ray install`
# and `scripts\ray start`.

$missing = @()
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { $missing += "Docker Desktop (https://docs.docker.com/get-docker/)" }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { $missing += "uv (https://docs.astral.sh/uv/)" }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { $missing += "pnpm (https://pnpm.io/installation)" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { $missing += "Node.js (https://nodejs.org/)" }

if ($missing.Count -gt 0) {
    Write-Host "Ray needs the following tools before it can install:"
    $missing | ForEach-Object { Write-Host "  - $_" }
    exit 1
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
& "$repoRoot\scripts\ray" install
& "$repoRoot\scripts\ray" start
