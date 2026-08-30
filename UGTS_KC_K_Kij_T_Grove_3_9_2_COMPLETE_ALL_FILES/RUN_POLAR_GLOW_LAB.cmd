@echo off
setlocal
cd /d "%~dp0"

set "UGTS_GLOW_PROJECT=build\polar-glow-lab\packed-polar-glow-burst-128-lut-subtle.json"
set "UGTS_GLOW_GENERATOR=examples\packed_polar_gpu_lab_3d\generate_recipe_variants.py"

if exist "%UGTS_GLOW_PROJECT%" goto open_editor

if not exist "build\polar-glow-lab" mkdir "build\polar-glow-lab"
where python >nul 2>nul
if not errorlevel 1 (
    python "%UGTS_GLOW_GENERATOR%" --count 128 --preset burst --polar-mode lut --bayer-mode subtle --glow-by-distance --glow-start-distance 0 --glow-end-distance 4 --glow-strength 1.25 --output "%UGTS_GLOW_PROJECT%"
    if errorlevel 1 goto generation_failed
    goto open_editor
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%UGTS_GLOW_GENERATOR%" --count 128 --preset burst --polar-mode lut --bayer-mode subtle --glow-by-distance --glow-start-distance 0 --glow-end-distance 4 --glow-strength 1.25 --output "%UGTS_GLOW_PROJECT%"
    if errorlevel 1 goto generation_failed
    goto open_editor
)

echo.
echo The Glow lab needs Python 3.11 or newer.
echo Install Python, then double-click this file again.
echo.
pause
exit /b 1

:open_editor
call "RUN_UGTS_STUDIO.cmd" "%UGTS_GLOW_PROJECT%"
exit /b %errorlevel%

:generation_failed
echo.
echo UGTS could not create the Glow-by-distance sample project.
echo Read the message above, then double-click this file again.
echo.
pause
exit /b 1
