@echo off
setlocal

set "NANOPREDICT_ROOT=%~dp0"
set "NANOPREDICT_ENV=%NANOPREDICT_ROOT%.nanopredict-env"
set "NANOPREDICT_PYTHON=%NANOPREDICT_ENV%\Scripts\python.exe"
set "NANOPREDICT_READY=%NANOPREDICT_ENV%\.ready"

if not exist "%NANOPREDICT_READY%" (
    echo First run: creating the private Nanopredict environment...
    where py.exe >nul 2>nul
    if errorlevel 1 (
        echo Python was not found. Install 64-bit Python 3.9-3.12 and try again.
        exit /b 1
    )
    py.exe -3 -c "import sys; raise SystemExit(0 if (3, 9) <= sys.version_info[:2] < (3, 13) else 1)"
    if errorlevel 1 (
        echo Nanopredict requires 64-bit Python 3.9-3.12.
        exit /b 1
    )
    if not exist "%NANOPREDICT_PYTHON%" (
        py.exe -3 -m venv "%NANOPREDICT_ENV%"
        if errorlevel 1 exit /b 1
    )
    "%NANOPREDICT_PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
    "%NANOPREDICT_PYTHON%" -m pip install --editable "%NANOPREDICT_ROOT%."
    if errorlevel 1 exit /b 1
    type nul > "%NANOPREDICT_READY%"
)

"%NANOPREDICT_PYTHON%" -m nanopredict %*
