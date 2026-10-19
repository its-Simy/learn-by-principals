@echo off
rem One-command setup for Windows: runs setup.ps1 with the policy a fresh machine needs.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup failed; see above. If PowerShell refused to run the script, a machine policy
  echo overrides -ExecutionPolicy Bypass: in an elevated PowerShell run
  echo     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  if not defined CI pause
  exit /b 1
)
