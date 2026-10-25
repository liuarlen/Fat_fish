@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0app.py" %*
    goto :end
)
if exist "%~dp0..\pdf-translator\.venv\Scripts\python.exe" (
    "%~dp0..\pdf-translator\.venv\Scripts\python.exe" "%~dp0app.py" %*
    goto :end
)
python "%~dp0app.py" %*
:end
if errorlevel 1 pause
