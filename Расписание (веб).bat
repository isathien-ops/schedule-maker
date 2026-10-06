@echo off
rem ==========================================================================
rem Launcher of the web version: double-click it to start the local server
rem (web.py -> src\web\server.py), which opens the timetable page in the browser.
rem Python is looked up in this order: the project .venv
rem (.venv\Scripts\python.exe, see README), then python from PATH.
rem Keep this file pure ASCII: non-ASCII lines break cmd after chcp 65001.
rem ==========================================================================
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" web.py
) else (
    python web.py
)

rem Keep the window open after the server stops, so an error message can be read
pause
