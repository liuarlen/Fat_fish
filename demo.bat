@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py" --demo
    exit /b 0
)
if exist "%~dp0..\pdf-translator\.venv\Scripts\pythonw.exe" (
    start "" "%~dp0..\pdf-translator\.venv\Scripts\pythonw.exe" "%~dp0app.py" --demo
    exit /b 0
)
echo [YiPage PDF] Runtime not found. Please run install.bat first.
pause
exit /b 1
