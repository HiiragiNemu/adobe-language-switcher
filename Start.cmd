@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0switcher.py" gui
) else (
  python "%~dp0switcher.py" gui
)
if errorlevel 1 (
  echo.
  echo Requires Windows and Python 3.10+ with Tkinter.
  echo Download Python from https://www.python.org/downloads/windows/
  pause
)
