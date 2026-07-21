@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "MLT_PROJECT_ROOT=%~dp0"
if "%MLT_PROJECT_ROOT:~-1%"=="\" set "MLT_PROJECT_ROOT=%MLT_PROJECT_ROOT:~0,-1%"
set "VENV_PYTHON=%MLT_PROJECT_ROOT%\.venv\Scripts\python.exe"
set "RUN_DIR=%MLT_PROJECT_ROOT%\.run"
set "MLT_PID_FILE=%RUN_DIR%\server.pid"
set "MLT_STDOUT_LOG=%RUN_DIR%\server.stdout.log"
set "MLT_STDERR_LOG=%RUN_DIR%\server.stderr.log"
set "MLT_WORKER_PID_FILE=%RUN_DIR%\translation-worker.pid"
set "MLT_WORKER_STDERR_LOG=%RUN_DIR%\translation-worker.stderr.log"
set "MLT_DESKTOP_EXE=%MLT_PROJECT_ROOT%\desktop\node_modules\electron\dist\electron.exe"
set "MLT_DESKTOP_ENTRY=%MLT_PROJECT_ROOT%\desktop\main.cjs"
set "MLT_DESKTOP_PID_FILE=%RUN_DIR%\desktop.pid"
set "MLT_DESKTOP_READY_FILE=%RUN_DIR%\desktop.ready"
set "MLT_DESKTOP_STDOUT_LOG=%RUN_DIR%\desktop.stdout.log"
set "MLT_DESKTOP_STDERR_LOG=%RUN_DIR%\desktop.stderr.log"

if not defined MLT_HOST set "MLT_HOST=127.0.0.1"
if not defined MLT_PORT set "MLT_PORT=8765"
set "MLT_APP_URL=http://127.0.0.1:%MLT_PORT%/"
set "MLT_HEALTH_URL=http://127.0.0.1:%MLT_PORT%/api/health"
set "MLT_DIAGNOSTICS_URL=http://127.0.0.1:%MLT_PORT%/api/diagnostics"

cd /d "%MLT_PROJECT_ROOT%" || goto :project_error
if not exist "%VENV_PYTHON%" goto :venv_error
"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto :venv_version_error

if not exist "%RUN_DIR%" mkdir "%RUN_DIR%"
if errorlevel 1 goto :run_dir_error

if not exist "%MLT_PID_FILE%" goto :no_existing_pid
set /p EXISTING_PID=<"%MLT_PID_FILE%"
call :is_owned_process "%EXISTING_PID%"
if errorlevel 1 goto :stale_existing_pid
call :is_healthy_server "%EXISTING_PID%"
if errorlevel 1 goto :existing_server_unhealthy
echo VerbaRadar is already running. PID: %EXISTING_PID%
call :wait_for_worker
call :open_app
exit /b 0

:stale_existing_pid
echo Removing a stale project PID file.
del /q "%MLT_PID_FILE%" >nul 2>&1

:no_existing_pid

echo Starting VerbaRadar on %MLT_APP_URL%
echo Logs:
echo   %MLT_STDOUT_LOG%
echo   %MLT_STDERR_LOG%

powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%MLT_PROJECT_ROOT%\scripts\start_project_server.ps1" -ProjectRoot "%MLT_PROJECT_ROOT%" -PythonPath "%VENV_PYTHON%" -HostAddress "%MLT_HOST%" -Port %MLT_PORT% -PidFile "%MLT_PID_FILE%" -StdoutLog "%MLT_STDOUT_LOG%" -StderrLog "%MLT_STDERR_LOG%"
if errorlevel 1 goto :start_error

set /p SERVER_PID=<"%MLT_PID_FILE%"
set "WAIT_COUNT=0"

:wait_for_server
call :is_healthy_server "%SERVER_PID%"
if not errorlevel 1 goto :server_ready

call :is_owned_process "%SERVER_PID%"
if errorlevel 1 goto :server_exited

set /a WAIT_COUNT+=1
if %WAIT_COUNT% GEQ 90 goto :readiness_timeout
>nul 2>&1 timeout /t 1 /nobreak
goto :wait_for_server

:server_ready
echo Server is ready. PID: %SERVER_PID%
call :wait_for_worker
call :open_app
exit /b 0

:open_app
if /I "%MLT_DESKTOP%"=="0" goto :open_browser
if not exist "%MLT_DESKTOP_EXE%" (
  echo INFO: Native transparent overlays are not installed.
  echo       Run setup_desktop_overlay.bat when you want desktop transparency.
  goto :open_browser
)
echo Opening the native desktop UI...
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%MLT_PROJECT_ROOT%\scripts\start_desktop.ps1" -ProjectRoot "%MLT_PROJECT_ROOT%" -ExecutablePath "%MLT_DESKTOP_EXE%" -EntryPath "%MLT_DESKTOP_ENTRY%" -AppUrl "%MLT_APP_URL%" -PidFile "%MLT_DESKTOP_PID_FILE%" -ReadyFile "%MLT_DESKTOP_READY_FILE%" -StdoutLog "%MLT_DESKTOP_STDOUT_LOG%" -StderrLog "%MLT_DESKTOP_STDERR_LOG%"
if not errorlevel 1 exit /b 0
echo WARNING: Native desktop startup failed. Falling back to the default browser.
echo Desktop log:
echo   %MLT_DESKTOP_STDERR_LOG%

:open_browser
echo Opening the default browser...
start "" "%MLT_APP_URL%"
exit /b 0

:is_owned_process
set "MLT_CHECK_PID=%~1"
powershell -NoProfile -NonInteractive -Command "$processId=0; if (-not [int]::TryParse($env:MLT_CHECK_PID,[ref]$processId)) { exit 1 }; $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $processId) -ErrorAction SilentlyContinue; if ($null -eq $p -or [string]::IsNullOrWhiteSpace($p.CommandLine)) { exit 1 }; $cmd=[string]$p.CommandLine; if ($cmd.IndexOf('backend.app.main:app',[StringComparison]::OrdinalIgnoreCase) -ge 0 -and $cmd.IndexOf($env:MLT_PROJECT_ROOT,[StringComparison]::OrdinalIgnoreCase) -ge 0) { exit 0 }; exit 1" >nul 2>&1
exit /b %ERRORLEVEL%

:is_healthy_server
set "MLT_CHECK_PID=%~1"
powershell -NoProfile -NonInteractive -Command "$processId=0; if (-not [int]::TryParse($env:MLT_CHECK_PID,[ref]$processId)) { exit 1 }; $listeners=@(Get-NetTCPConnection -LocalPort ([int]$env:MLT_PORT) -State Listen -ErrorAction SilentlyContinue); if ($listeners.Count -ne 1 -or [int]$listeners[0].OwningProcess -ne $processId) { exit 1 }; try { $r=Invoke-RestMethod -Uri $env:MLT_HEALTH_URL -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %ERRORLEVEL%

:wait_for_worker
set "WORKER_WAIT_COUNT=0"
:wait_for_worker_loop
powershell -NoProfile -NonInteractive -Command "try { $r=Invoke-RestMethod -Uri $env:MLT_DIAGNOSTICS_URL -TimeoutSec 2; $w=$r.translation_worker; if ($w.available -eq $true -and $w.state -eq 'ready') { exit 0 }; if ($w.configured -eq $false -or $w.state -eq 'unavailable') { exit 2 } } catch {}; exit 1" >nul 2>&1
if "%ERRORLEVEL%"=="0" goto :worker_ready
if "%ERRORLEVEL%"=="2" goto :worker_unavailable
set /a WORKER_WAIT_COUNT+=1
if %WORKER_WAIT_COUNT% GEQ 90 goto :worker_recovery_pending
>nul 2>&1 timeout /t 1 /nobreak
goto :wait_for_worker_loop

:worker_ready
if not exist "%MLT_WORKER_PID_FILE%" goto :worker_ready_without_pid
set /p WORKER_PID=<"%MLT_WORKER_PID_FILE%"
echo Local translation Worker is ready. PID: %WORKER_PID%
exit /b 0

:worker_ready_without_pid
echo Local translation Worker is ready.
exit /b 0

:worker_unavailable
echo WARNING: The local translation Worker is not configured or installed.
echo Original transcription remains available.
exit /b 0

:worker_recovery_pending
echo WARNING: The local translation Worker is still recovering or unavailable.
echo Original transcription remains available. Worker log:
echo   %MLT_WORKER_STDERR_LOG%
exit /b 0

:show_log_tail
echo.
echo Last server errors:
powershell -NoProfile -NonInteractive -Command "if (Test-Path -LiteralPath $env:MLT_STDERR_LOG) { Get-Content -LiteralPath $env:MLT_STDERR_LOG -Tail 30 }" 2>nul
exit /b 0

:cleanup_failed_start
call "%MLT_PROJECT_ROOT%\stop_all.bat" >nul 2>&1
exit /b 0

:project_error
echo ERROR: Could not enter the project directory: %MLT_PROJECT_ROOT%
exit /b 1

:existing_server_unhealthy
echo ERROR: The saved project server PID is owned but its health or port ownership check failed.
echo Run stop_all.bat, then start_all.bat again. No duplicate server was started.
exit /b 1

:venv_error
echo ERROR: Project .venv was not found.
echo Run setup.bat first.
exit /b 1

:venv_version_error
echo ERROR: Project .venv is not using Python 3.11.
echo Review the environment, then run setup.bat.
exit /b 1

:run_dir_error
echo ERROR: Could not create the project-local .run directory.
exit /b 1

:start_error
echo ERROR: The FastAPI process could not be started.
call :show_log_tail
exit /b 1

:server_exited
echo ERROR: The server process exited before becoming ready.
call :show_log_tail
call :cleanup_failed_start
exit /b 1

:readiness_timeout
echo ERROR: The server did not become ready within 90 seconds.
echo The started project process will be stopped; no other Python process is affected.
call :show_log_tail
call :cleanup_failed_start
exit /b 1
