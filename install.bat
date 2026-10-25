@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo   YiPage PDF - Install dependencies
echo ============================================================
echo.

if exist "%~dp0.venv\Scripts\python.exe" goto :install

set "PY="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; print(sys.version)" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo Python was not found. Install Python 3.9 - 3.12 and enable "Add to PATH".
    pause
    exit /b 1
)

echo Creating virtual environment: .venv ...
%PY% -m venv .venv
if errorlevel 1 (
    echo Failed to create the virtual environment.
    pause
    exit /b 1
)

:install
echo Installing dependencies - this may take 1-3 minutes ...
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo Dependency installation failed. Check the network and try again.
    pause
    exit /b 1
)

echo.
echo Installation complete.
echo Double-click run.bat to start, or demo.bat for the offline sample.
pause
