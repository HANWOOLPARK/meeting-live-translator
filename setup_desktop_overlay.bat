@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

echo ============================================================
echo VerbaRadar - Native transparent overlay setup
echo ============================================================
echo This installs a portable Node runtime and Electron only inside
echo this project. It does not require administrator rights.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\setup_desktop_overlay.ps1" -ProjectRoot "%PROJECT_ROOT%"
if errorlevel 1 (
  echo.
  echo ERROR: Native overlay setup failed.
  echo The normal browser UI and caption pop-up remain available.
  exit /b 1
)

echo.
echo Native transparent overlays are ready.
echo Run start_all.bat and use the caption or Radar result window button.
exit /b 0
