@echo off
REM One-click Windows launcher for Ray.
REM Place this batch file in the repo root, then double-click it.

cd /d "%~dp0\.."
python scripts\ray start
pause
