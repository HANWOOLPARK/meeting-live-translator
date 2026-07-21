@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "LOCAL_OPTION=%~1"

if /I "%LOCAL_OPTION%"=="/?" goto :usage
if defined LOCAL_OPTION if /I not "%LOCAL_OPTION%"=="/local" if /I not "%LOCAL_OPTION%"=="/no-local" goto :usage_error

echo ============================================================
echo VerbaRadar - Lite setup
echo ============================================================
echo Project: %PROJECT_ROOT%
echo This script creates only project-local virtual environments.
echo It does not request administrator rights or change Windows settings.
echo.

cd /d "%PROJECT_ROOT%" || goto :project_error
if not exist "backend\requirements.txt" goto :requirements_error

set "PYTHON311="
where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON311 set "PYTHON311=%%I"
)
if defined PYTHON311 call :verify_python "%PYTHON311%"

if not defined PYTHON311 call :try_python "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON311 call :try_python "%ProgramFiles%\Python311\python.exe"
if not defined PYTHON311 call :try_python "%ProgramFiles(x86)%\Python311\python.exe"
if not defined PYTHON311 call :try_python "C:\Python311\python.exe"

if not defined PYTHON311 (
  for /f "delims=" %%I in ('where python 2^>nul') do if not defined PYTHON311 call :try_python "%%I"
)

if not defined PYTHON311 goto :python_error

echo [Core 1/8] Python 3.11 found:
"%PYTHON311%" --version
if errorlevel 1 goto :python_error

if exist ".venv\Scripts\python.exe" (
  echo [Core 2/8] Existing project .venv found. Verifying it...
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
  if errorlevel 1 goto :venv_version_error
) else (
  echo [Core 2/8] Creating project .venv with Python 3.11...
  "%PYTHON311%" -m venv "%PROJECT_ROOT%\.venv"
  if errorlevel 1 goto :venv_create_error
)

call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
if errorlevel 1 goto :activation_error

echo [Core 3/8] Virtual environment Python and pip:
python --version
python -m pip --version
if errorlevel 1 goto :pip_error

echo [Core 4/8] Updating pip inside .venv...
python -m pip install --upgrade pip
if errorlevel 1 goto :pip_upgrade_error

echo [Core 5/8] Installing backend requirements inside .venv...
python -m pip install -r "backend\requirements.txt"
if errorlevel 1 goto :package_error

echo [Core 6/8] Running core import checks...
python -c "import fastapi, uvicorn, faster_whisper, pyaudiowpatch, numpy, websockets, dotenv, openai; from backend.app.main import app; print('Core imports: OK'); print('OpenAI SDK:', openai.__version__); print('FastAPI app:', app.title)"
if errorlevel 1 goto :import_error

echo [Core 7/8] Checking optional runtime tools...
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo WARNING: ffmpeg was not found on PATH. Live PCM capture can still run.
) else (
  for /f "delims=" %%I in ('where ffmpeg') do echo ffmpeg: %%I
  ffmpeg -version 2>nul | findstr /b /c:"ffmpeg version"
)

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo INFO: nvidia-smi was not found. The app will use CPU int8 if CUDA model initialization is unavailable.
) else (
  echo NVIDIA information:
  nvidia-smi
)
python -c "import ctranslate2; print('CTranslate2:', ctranslate2.__version__); print('CUDA devices reported by CTranslate2:', ctranslate2.get_cuda_device_count())"
if errorlevel 1 echo WARNING: CTranslate2 CUDA probe failed. Runtime will still attempt CUDA safely and fall back to CPU int8.

echo [Core 8/8] Inspecting audio devices through the application adapter...
python "scripts\check_audio_devices.py"
if errorlevel 1 (
  set "AUDIO_CHECK_FAILED=1"
  echo WARNING: Audio device inspection did not complete successfully.
  echo          Review the message above, then retry after checking Windows audio devices.
) else (
  set "AUDIO_CHECK_FAILED=0"
)

if exist ".env" goto :env_ready
copy /y ".env.example" ".env" >nul
if errorlevel 1 goto :env_create_error
echo Created .env from .env.example.
echo Add only your own API keys before enabling external Providers.

:env_ready
set "INSTALL_LOCAL="
if /I "%LOCAL_OPTION%"=="/local" set "INSTALL_LOCAL=Y"
if /I "%LOCAL_OPTION%"=="/no-local" set "INSTALL_LOCAL=N"
if defined INSTALL_LOCAL goto :local_choice_ready

echo.
echo Optional local translation:
echo   - Downloads the pinned M2M100 source and creates a ~500 MB int8 model.
echo   - Temporarily requires about 6 GiB of free space during conversion.
echo   - The temporary source, Torch environment, and download cache are removed.
set /p "INSTALL_LOCAL=Install local M2M100 translation now? [y/N]: "

:local_choice_ready
if /I not "%INSTALL_LOCAL%"=="Y" if /I not "%INSTALL_LOCAL%"=="YES" goto :local_skipped
call "%PROJECT_ROOT%\setup_local_translation.bat" /install "%PYTHON311%"
if errorlevel 1 goto :local_install_error
set "LOCAL_RESULT=READY"
goto :setup_complete

:local_skipped
set "LOCAL_RESULT=SKIPPED - API translation and original transcription remain available"

:setup_complete

echo.
echo ============================================================
echo Setup completed.
echo Start the app with: start_all.bat
echo Optional native transparent overlays: setup_desktop_overlay.bat
echo Local translation: %LOCAL_RESULT%
if "%AUDIO_CHECK_FAILED%"=="1" echo Audio hardware check: WARNING - manual confirmation is still required.
echo ============================================================
exit /b 0

:usage
echo Usage:
echo   setup.bat             Interactive optional local-model choice
echo   setup.bat /local      Install core and local M2M100 translation
echo   setup.bat /no-local   Install the Lite core only
exit /b 0

:usage_error
echo ERROR: Unsupported option: %LOCAL_OPTION%
echo Use setup.bat /? for supported options.
exit /b 1

:verify_python
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if errorlevel 1 set "PYTHON311="
exit /b 0

:try_python
if not exist "%~1" exit /b 0
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "PYTHON311=%~1"
exit /b 0

:project_error
echo ERROR: Could not enter the project directory:
echo        %PROJECT_ROOT%
exit /b 1

:requirements_error
echo ERROR: backend\requirements.txt was not found under:
echo        %PROJECT_ROOT%
exit /b 1

:env_create_error
echo ERROR: Could not create .env from .env.example.
exit /b 1

:local_install_error
echo.
echo ERROR: The optional local translation installation failed.
echo Core setup completed, so original transcription and API Providers can still run.
echo Retry later with: setup_local_translation.bat
exit /b 1

:python_error
echo ERROR: A usable Python 3.11 installation was not found.
echo Checked: py -3.11, the current user's Python311 folder, Program Files, C:\Python311, and PATH.
echo Install Python 3.11 for the current user, then run setup.bat again.
exit /b 1

:venv_version_error
echo ERROR: The existing .venv was not created with Python 3.11.
echo Remove or rename only this project's .venv after reviewing its contents, then rerun setup.bat.
exit /b 1

:venv_create_error
echo ERROR: Could not create the project .venv with Python 3.11.
exit /b 1

:activation_error
echo ERROR: Could not activate .venv\Scripts\activate.bat.
exit /b 1

:pip_error
echo ERROR: pip is unavailable inside the project .venv.
exit /b 1

:pip_upgrade_error
echo ERROR: pip update failed. Check network/proxy output above. The global Python was not modified.
exit /b 1

:package_error
echo ERROR: Package installation failed. Check the package and network error above.
echo The failure is confined to this project's .venv.
exit /b 1

:import_error
echo ERROR: A required package could not be imported from the project .venv.
echo Review the Python traceback above and rerun setup.bat after resolving it.
exit /b 1
