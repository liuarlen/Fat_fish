@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0env\Scripts\python.exe" set "PY=%~dp0env\Scripts\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0..\pdf-translator\.venv\Scripts\python.exe" set "PY=%~dp0..\pdf-translator\.venv\Scripts\python.exe"
if not defined PY (
    echo Python runtime not found. Run install.bat first.
    pause
    exit /b 1
)

echo [1/2] Building with PyInstaller...
"%PY%" -m PyInstaller --noconfirm --clean --distpath "%~dp0dist" --workpath "%~dp0build" "%~dp0YiPagePDF.spec"
if errorlevel 1 goto :fail

echo [2/2] Done.
echo Output: %~dp0dist\Fat_fish\Fat_fish.exe
pause
exit /b 0

:fail
echo Build failed.
pause
exit /b 1
