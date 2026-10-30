@echo off
setlocal EnableExtensions
title Build Dungeon Within Save Editor

cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem Locate Python (set DW_PYTHON to override)
rem ---------------------------------------------------------------------------
set "PY="
if defined DW_PYTHON if exist "%DW_PYTHON%" set "PY=%DW_PYTHON%"

if not defined PY (
    set "BUNDLED=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
    if exist "%BUNDLED%" set "PY=%BUNDLED%"
)
if not defined PY (
    where py.exe >nul 2>nul
    if not errorlevel 1 set "PY=py"
)
if not defined PY (
    where python.exe >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo [ERROR] No Python interpreter found. Install Python 3.10+ or set DW_PYTHON.
    pause
    exit /b 1
)

echo Using Python: %PY%
"%PY%" -c "import sys; print(sys.version)"

rem ---------------------------------------------------------------------------
rem Dependencies
rem ---------------------------------------------------------------------------
"%PY%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    "%PY%" -m pip install --disable-pip-version-check pyinstaller
)
"%PY%" -c "import frida" >nul 2>nul
if errorlevel 1 (
    echo Installing frida...
    "%PY%" -m pip install --disable-pip-version-check frida
)

rem ---------------------------------------------------------------------------
rem Build (one-file, windowed)
rem ---------------------------------------------------------------------------
echo Building...
"%PY%" -m PyInstaller --noconfirm --clean --distpath "%~dp0dist" --workpath "%~dp0work" "%~dp0DungeonWithinSaveEditor.spec"
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See the output above.
    pause
    exit /b 1
)

echo.
echo Done: "%~dp0dist\DungeonWithinSaveEditor.exe"
pause
exit /b 0
