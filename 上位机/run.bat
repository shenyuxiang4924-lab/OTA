@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHON_CMD="
set "PYTHONW_CMD="
set "PY_CHECK_FILE=%TEMP%\host_computer_python_check.txt"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
    if exist ".venv\Scripts\pythonw.exe" set "PYTHONW_CMD=.venv\Scripts\pythonw.exe"
    goto :found_python
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -c "import sys; print('PY_OK' if sys.version_info >= (3, 10) else 'PY_OLD')" > "%PY_CHECK_FILE%" 2>nul
    set "PY_CHECK="
    set /p PY_CHECK=<"%PY_CHECK_FILE%" 2>nul
    if "!PY_CHECK!"=="PY_OK" (
        set "PYTHON_CMD=py -3"
        where pyw >nul 2>nul
        if !errorlevel!==0 set "PYTHONW_CMD=pyw -3"
        goto :found_python
    )
)

where python >nul 2>nul
if %errorlevel%==0 (
    python -c "import sys; print('PY_OK' if sys.version_info >= (3, 10) else 'PY_OLD')" > "%PY_CHECK_FILE%" 2>nul
    set "PY_CHECK="
    set /p PY_CHECK=<"%PY_CHECK_FILE%" 2>nul
    if "!PY_CHECK!"=="PY_OK" (
        set "PYTHON_CMD=python"
        for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%P"
        for %%P in ("!PYTHON_EXE!") do set "PYTHONW_CANDIDATE=%%~dpPpythonw.exe"
        if exist "!PYTHONW_CANDIDATE!" set "PYTHONW_CMD=!PYTHONW_CANDIDATE!"
        goto :found_python
    )
)

echo Python was not found.
echo Install Python 3.10 or newer and enable "Add python.exe to PATH".
echo Download: https://www.python.org/downloads/windows/
goto :fail

:found_python
echo Python command: %PYTHON_CMD%
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency install failed.
    echo Try running this command manually:
    echo %PYTHON_CMD% -m pip install -r requirements.txt
    goto :fail
)

if not defined PYTHONW_CMD set "PYTHONW_CMD=%PYTHON_CMD%"
start "" %PYTHONW_CMD% "%CD%\main.py"
goto :end

:fail
echo.
pause

:end
endlocal
