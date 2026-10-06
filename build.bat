@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Ready build: dist\<name>\<name>.exe runs without Python or a compiler installed.
rem Needs .venv with requirements.txt and pyinstaller; the solver is compiled first.
rem Temporary build files go to %TEMP%\schedule-build, not into the project.
rem Only the program name below is in Russian: other non-ASCII lines confuse cmd after chcp 65001.

rem Step 0: stop leftover solve.exe processes. A solver started by an old build of the program
rem could outlive the closed program window and keep dist\...\solve.exe locked, and then
rem PyInstaller failed to delete the old dist folder (the first build after closing the program
rem used to fail, the second one passed). New builds close their solver together with the program.
taskkill /F /IM solve.exe >nul 2>nul

rem Step 1: rebuild the solver solve.exe (it is bundled into the exe below).
call "%~dp0compile.bat"
if errorlevel 1 (echo BUILD FAILED: solver & exit /b 1)

rem Step 2: pack web.py, the Python server and all data into one folder with PyInstaller.
rem   --console      keep a console window: it shows the server log and the address
rem   --add-data     src\files (bundles, defaults) and src\web\static (the web page)
rem   --add-binary   the solver solve.exe, placed under src\modules inside the bundle
rem The result is dist\<name>\<name>.exe plus its _internal folder.
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --console --name "Расписание" ^
    --workpath "%TEMP%\schedule-build" --specpath "%TEMP%\schedule-build" ^
    --add-data "%~dp0src\files;src\files" ^
    --add-data "%~dp0src\web\static;src\web\static" ^
    --add-binary "%~dp0src\modules\solve.exe;src\modules" ^
    "%~dp0web.py"
if errorlevel 1 (echo BUILD FAILED: PyInstaller & exit /b 1)

echo.
echo Done: dist
