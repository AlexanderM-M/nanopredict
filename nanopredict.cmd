@echo off
setlocal

set "NANOPREDICT_ROOT=%~dp0"
set "NANOPREDICT_ENV=%NANOPREDICT_ROOT%.nanopredict-env"
set "NANOPREDICT_PYTHON=%NANOPREDICT_ENV%\Scripts\python.exe"
set "NANOPREDICT_READY=%NANOPREDICT_ENV%\.ready"

if not exist "%NANOPREDICT_PYTHON%" (
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
    py.exe -3 -m venv "%NANOPREDICT_ENV%"
    if errorlevel 1 exit /b 1
    "%NANOPREDICT_PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
)

for /f "delims=" %%H in ('"%NANOPREDICT_PYTHON%" -c "import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())" "%NANOPREDICT_ROOT%pyproject.toml"') do set "NANOPREDICT_CONFIG_HASH=%%H"
set "NANOPREDICT_READY_HASH="
if exist "%NANOPREDICT_READY%" set /p NANOPREDICT_READY_HASH=<"%NANOPREDICT_READY%"

if not "%NANOPREDICT_READY_HASH%"=="%NANOPREDICT_CONFIG_HASH%" (
    echo Installing or updating Nanopredict...
    "%NANOPREDICT_PYTHON%" -m pip install "setuptools>=77" wheel
    if errorlevel 1 exit /b 1
    "%NANOPREDICT_PYTHON%" -m pip install --no-build-isolation --editable "%NANOPREDICT_ROOT%."
    if errorlevel 1 exit /b 1
    >"%NANOPREDICT_READY%" echo %NANOPREDICT_CONFIG_HASH%
)

"%NANOPREDICT_PYTHON%" -m nanopredict %*
