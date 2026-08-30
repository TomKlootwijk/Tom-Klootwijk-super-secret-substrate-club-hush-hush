@echo off
setlocal
cd /d "%~dp0"

set "UGTS_GROW_PROJECT=build\polar-grow-lab\packed-polar-grow-burst-128-lut-subtle.json"
set "UGTS_GROW_GENERATOR=examples\packed_polar_gpu_lab_3d\generate_recipe_variants.py"

if exist "%UGTS_GROW_PROJECT%" goto validate_existing

goto generate_project

:validate_existing
where python >nul 2>nul
if not errorlevel 1 (
    python "%UGTS_GROW_GENERATOR%" --validate-existing --output "%UGTS_GROW_PROJECT%"
    if errorlevel 1 goto validation_failed
    goto open_editor
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%UGTS_GROW_GENERATOR%" --validate-existing --output "%UGTS_GROW_PROJECT%"
    if errorlevel 1 goto validation_failed
    goto open_editor
)

goto python_missing

:generate_project
if not exist "build\polar-grow-lab" mkdir "build\polar-grow-lab"
where python >nul 2>nul
if not errorlevel 1 (
    python "%UGTS_GROW_GENERATOR%" --count 128 --preset burst --polar-mode lut --bayer-mode subtle --glow-by-distance --grow-glowing-copies --glow-start-distance 0 --glow-end-distance 4 --glow-strength 1.25 --output "%UGTS_GROW_PROJECT%"
    if errorlevel 1 goto generation_failed
    goto open_editor
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%UGTS_GROW_GENERATOR%" --count 128 --preset burst --polar-mode lut --bayer-mode subtle --glow-by-distance --grow-glowing-copies --glow-start-distance 0 --glow-end-distance 4 --glow-strength 1.25 --output "%UGTS_GROW_PROJECT%"
    if errorlevel 1 goto generation_failed
    goto open_editor
)

:python_missing
echo.
echo The Grow lab needs Python 3.11 or newer.
echo Install Python, then double-click this file again.
echo.
pause
exit /b 1

:open_editor
call "RUN_UGTS_STUDIO.cmd" "%UGTS_GROW_PROJECT%"
exit /b %errorlevel%

:generation_failed
echo.
echo UGTS could not create the Grow-glowing-copies sample project.
echo Read the message above, then double-click this file again.
echo.
pause
exit /b 1

:validation_failed
echo.
echo The existing Grow lab is stale, partial, or is not KCPR v4 Grow content.
echo Move or rename it, then double-click this file to generate a fresh sample.
echo.
pause
exit /b 1
