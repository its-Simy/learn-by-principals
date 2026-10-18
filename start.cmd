@echo off
rem Start BrightLearn:  start.cmd [--port 8765] [--no-open]   (or double-click it)
setlocal
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\pnpm;%PATH%"
set "PYTHONUTF8=1"
set "UV_MANAGED_PYTHON=1"
if not exist ".venv\pyvenv.cfg" (
  echo No Python environment yet: run setup.cmd first.
  pause
  exit /b 1
)
uv run --no-sync brightlearn start %*
if errorlevel 1 (
  echo.
  echo BrightLearn did not start; see above.
  pause
  exit /b 1
)
