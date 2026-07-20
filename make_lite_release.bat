@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

cd /d "%PROJECT_ROOT%" || exit /b 1
echo Building a secret-free Meeting Live Translator Lite ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\build_lite_release.ps1"
if errorlevel 1 (
  echo ERROR: Lite release creation failed. No package should be shared.
  exit /b 1
)
echo.
echo Share only the ZIP created under:
echo   %PROJECT_ROOT%\dist
exit /b 0
