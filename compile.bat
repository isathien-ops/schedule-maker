@echo off

rem ==========================================================================
rem compile.bat - builds the timetable solver src\modules\solve.exe
rem from src\modules\solve.cpp with g++ (MinGW-w64, C++17, -O2).
rem The exe is linked statically, so it runs on any Windows machine without
rem MinGW DLLs. The web server (src\web\build.py) starts solve.exe once for
rem every variant it builds. build.bat calls this script first.
rem Keep this file pure ASCII: non-ASCII lines break cmd after chcp 65001.
rem Exit code: 0 on success, 1 if the compiler failed.
rem ==========================================================================

rem UTF-8 console, and work from the folder of this script (the project root)
chcp 65001 > nul
cd /d "%~dp0"

rem If g++ is not on PATH, use the WinLibs MinGW installed by winget
rem (winget install BrechtSanders.WinLibs.POSIX.UCRT) from its default folder
set "WINLIBS=%LOCALAPPDATA%\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin"
where g++ >nul 2>nul || set "PATH=%WINLIBS%;%PATH%"

rem Compile; the third-party headers CLI11.hpp and json.hpp come from src\modules\libs
g++ -std=c++17 -O2 -static-libgcc -static-libstdc++ -static src/modules/solve.cpp -o src/modules/solve.exe
if errorlevel 1 (echo compile failed & exit /b 1)

echo done
