@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "MODE=%~1"
set "PYTHON311=%~2"
set "RUNTIME_PYTHON=%PROJECT_ROOT%\.venv-translation\Scripts\python.exe"
set "MODEL_DIR=%PROJECT_ROOT%\models\translation\m2m100_418m-int8"

if not defined MODE set "MODE=/install"
if /I "%MODE%"=="/?" goto :usage
if /I "%MODE%"=="/check" goto :check
if /I not "%MODE%"=="/install" goto :usage_error

cd /d "%PROJECT_ROOT%" || goto :project_error
if defined PYTHON311 goto :verify_python

where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON311 set "PYTHON311=%%I"
)
if not defined PYTHON311 if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON311=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON311 goto :python_error

:verify_python
"%PYTHON311%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto :python_error

echo ============================================================
echo WhyKaigi - optional local translation setup
echo ============================================================
echo The runtime is installed only in .venv-translation.
echo If the model is absent, the pinned M2M100 source is downloaded
echo and converted in a temporary environment that is removed afterward.
echo Torch is not installed in the main .venv.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\install_local_translation.ps1" -ProjectRoot "%PROJECT_ROOT%" -PythonPath "%PYTHON311%"
if errorlevel 1 goto :install_error
exit /b 0

:check
cd /d "%PROJECT_ROOT%" || goto :project_error
if not exist "%RUNTIME_PYTHON%" goto :runtime_error
if not exist "%MODEL_DIR%\model.bin" goto :model_error
if not exist "%MODEL_DIR%\sentencepiece.bpe.model" goto :model_error
"%RUNTIME_PYTHON%" -c "import sys, importlib.util; assert sys.version_info[:2] == (3, 11); assert importlib.util.find_spec('torch') is None; import ctranslate2, transformers, sentencepiece, psutil; from pathlib import Path; p=Path(r'%MODEL_DIR%'); required=('model.bin','config.json','shared_vocabulary.json','sentencepiece.bpe.model','vocab.json','tokenizer_config.json'); assert all((p/name).is_file() for name in required); assert ctranslate2.contains_model(str(p)); print('Local translation runtime and model: OK')"
if errorlevel 1 goto :check_error
exit /b 0

:usage
echo Usage:
echo   setup_local_translation.bat          Install or repair runtime/model
echo   setup_local_translation.bat /check   Validate without downloading
exit /b 0

:usage_error
echo ERROR: Unsupported option: %MODE%
echo Use setup_local_translation.bat /? for supported options.
exit /b 1

:project_error
echo ERROR: Could not enter the project directory.
exit /b 1

:python_error
echo ERROR: A usable Python 3.11 installation was not found.
echo Install Python 3.11 for the current user, then retry.
exit /b 1

:runtime_error
echo ERROR: .venv-translation is not installed.
echo Run setup_local_translation.bat to install it.
exit /b 1

:model_error
echo ERROR: The M2M100 CTranslate2 model is not installed or is incomplete.
echo Run setup_local_translation.bat to download and convert it.
exit /b 1

:check_error
echo ERROR: The isolated local translation installation check failed.
exit /b 1

:install_error
echo ERROR: Local translation installation did not complete.
echo The main app can still run with local translation unavailable.
exit /b 1
