@echo off
setlocal
cd /d "%~dp0"

set "PYW="
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYW if exist "%~dp0..\pdf-translator\.venv\Scripts\pythonw.exe" set "PYW=%~dp0..\pdf-translator\.venv\Scripts\pythonw.exe"

if not defined PYW (
    echo [YiPage PDF] Runtime not found.
    echo Please run install.bat first.
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0app.py" %*
exit /b 0
