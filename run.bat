@echo off
setlocal EnableExtensions
title Dungeon Within Save Editor
cd /d "%~dp0"

set "PY="
if defined DW_PYTHON if exist "%DW_PYTHON%" set "PY=%DW_PYTHON%"
if not defined PY (
    where pythonw.exe >nul 2>nul
    if not errorlevel 1 set "PY=pythonw"
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

start "" %PY% "%~dp0main.py" %*
exit /b 0
