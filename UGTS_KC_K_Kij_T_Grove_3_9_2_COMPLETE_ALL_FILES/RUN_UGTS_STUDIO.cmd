@echo off
setlocal
cd /d "%~dp0"

set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONPATH=%CD%\src"
set "UGTS_PY="

where python >nul 2>nul
if not errorlevel 1 set "UGTS_PY=python"
if defined UGTS_PY goto check_editor

where py >nul 2>nul
if not errorlevel 1 set "UGTS_PY=py -3"
if defined UGTS_PY goto check_editor

echo.
echo UGTS Studio could not find Python 3.
echo Install Python 3.11 or newer, then double-click this file again.
echo.
pause
exit /b 1

:check_editor
%UGTS_PY% -c "import PySide6, ugts_kc3" >nul 2>nul
if not errorlevel 1 goto launch_editor
if "%UGTS_LAUNCHER_SMOKE%"=="1" (
    echo UGTS Studio launcher found Python, but the editor dependency is missing.
    exit /b 2
)

echo.
echo UGTS Studio needs its editor package once before first launch.
choice /M "Install it now"
if errorlevel 2 exit /b 1
echo.
%UGTS_PY% -m pip install -e ".[editor]"
if errorlevel 1 goto install_failed

:launch_editor
if "%UGTS_LAUNCHER_SMOKE%"=="1" (
    echo UGTS Studio launcher is ready.
    exit /b 0
)

set "UGTS_PY_EXE="
for /f "delims=" %%P in ('%UGTS_PY% -c "import sys; print(sys.executable)"') do set "UGTS_PY_EXE=%%P"
if not defined UGTS_PY_EXE goto launch_failed
for %%P in ("%UGTS_PY_EXE%") do set "UGTS_PYW=%%~dpPpythonw.exe"

if exist "%UGTS_PYW%" (
    start "UGTS Studio" "%UGTS_PYW%" -m ugts_kc3 editor %*
) else (
    start "UGTS Studio" "%UGTS_PY_EXE%" -m ugts_kc3 editor %*
)
exit /b 0

:install_failed
echo.
echo The editor dependency installation did not finish.
echo Check the message above, then run this launcher again.
echo.
pause
exit /b 1

:launch_failed
echo.
echo Python was found, but its executable path could not be resolved.
echo.
pause
exit /b 1
