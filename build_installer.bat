@echo off
setlocal
cd /d "%~dp0"

set "ISCC="
where ISCC.exe >nul 2>nul
if not errorlevel 1 set "ISCC=ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo Inno Setup 6 was not found. Install it, then run this script again.
    exit /b 1
)

if not exist "%~dp0dist\Fat_fish\Fat_fish.exe" (
    echo Packaged app not found: dist\Fat_fish\Fat_fish.exe
    echo Run build_windows.bat first.
    exit /b 1
)

"%ISCC%" "%~dp0packaging\YiPagePDF.iss"
if errorlevel 1 exit /b 1

echo Installer created: %~dp0dist\Fat_fish_Setup_1.2.1.exe
exit /b 0
