@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "MLT_PROJECT_ROOT=%~dp0"
if "%MLT_PROJECT_ROOT:~-1%"=="\" set "MLT_PROJECT_ROOT=%MLT_PROJECT_ROOT:~0,-1%"
if not defined MLT_PORT set "MLT_PORT=8765"

cd /d "%MLT_PROJECT_ROOT%" || goto :project_error

powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%MLT_PROJECT_ROOT%\scripts\stop_project.ps1" -ProjectRoot "%MLT_PROJECT_ROOT%" -Port %MLT_PORT%
exit /b %ERRORLEVEL%

:project_error
echo ERROR: Could not enter the project directory: %MLT_PROJECT_ROOT%
exit /b 1
