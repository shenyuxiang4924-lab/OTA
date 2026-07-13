@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run run.bat once or create .venv first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo Dependency install failed.
    pause
    exit /b 1
)

".venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed --name "USART_CAN_上位机" --collect-submodules can.interfaces main.py
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo Built dist\USART_CAN_上位机.exe
pause
