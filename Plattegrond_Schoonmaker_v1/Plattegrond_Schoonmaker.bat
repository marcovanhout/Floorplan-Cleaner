@echo off
setlocal enabledelayedexpansion
title Plattegrond Schoonmaker

REM ============================================================
REM  Plattegrond Schoonmaker - dubbelklik of sleep een PDF hierop
REM ============================================================
REM  Dit bestand moet in dezelfde map staan als floorplan_cleaner.py
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "CLEANER=%SCRIPT_DIR%floorplan_cleaner.py"

if not exist "%CLEANER%" (
    echo FOUT: floorplan_cleaner.py niet gevonden in:
    echo   %SCRIPT_DIR%
    echo Zet dit bat-bestand in dezelfde map als floorplan_cleaner.py.
    echo.
    pause
    exit /b 1
)

REM --- Controleer of Python beschikbaar is ---
where python >nul 2>nul
if errorlevel 1 (
    echo FOUT: Python is niet gevonden.
    echo Installeer Python van https://www.python.org/downloads/
    echo en vink tijdens installatie "Add python.exe to PATH" aan.
    echo.
    pause
    exit /b 1
)

REM --- Bepaal het input-PDF-bestand ---
set "INPUT=%~1"

if "%INPUT%"=="" (
    echo Geen bestand meegegeven, kies een PDF in het venster...
    set "PICKER=%SCRIPT_DIR%PickPdf.ps1"
    for /f "usebackq delims=" %%F in (`powershell -NoProfile -ExecutionPolicy Bypass -File "!PICKER!"`) do (
        set "INPUT=%%F"
    )
)

if "%INPUT%"=="" (
    echo Geen bestand gekozen. Klaar.
    echo.
    pause
    exit /b 0
)

if not exist "%INPUT%" (
    echo FOUT: bestand niet gevonden:
    echo   %INPUT%
    echo.
    pause
    exit /b 1
)

REM --- Vraag of losse ruimte-PNG's ook gemaakt moeten worden ---
set "ROOMS_FLAG="
set "ASKROOMS=%SCRIPT_DIR%AskRooms.ps1"
if exist "%ASKROOMS%" (
    for /f "usebackq delims=" %%R in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%ASKROOMS%"`) do (
        if /i "%%R"=="yes" set "ROOMS_FLAG=--rooms"
    )
)

REM --- Output-bestandsnaam: zelfde map/naam, met _schoon.png ---
for %%A in ("%INPUT%") do (
    set "IN_DIR=%%~dpA"
    set "IN_NAME=%%~nA"
)
set "OUTPUT=%IN_DIR%%IN_NAME%_schoon.png"

echo.
echo Bezig met verwerken:
echo   Input:  %INPUT%
echo   Output: %OUTPUT%
if defined ROOMS_FLAG echo   Losse ruimte-PNG's: JA ^(map "%IN_NAME%_schoon_ruimtes"^)
echo.

python "%CLEANER%" "%INPUT%" "%OUTPUT%" %ROOMS_FLAG%
set "PYEXIT=%errorlevel%"

echo.
if not "%PYEXIT%"=="0" (
    echo Er ging iets mis tijdens het verwerken ^(zie de foutmelding hierboven^).
    if defined ROOMS_FLAG (
        echo Let op: de hoofdplattegrond kan alsnog goed zijn - alleen het
        echo onderdeel "losse ruimte-PNG's" kan zijn mislukt.
    )
) else if exist "%OUTPUT%" (
    echo KLAAR! Resultaat opgeslagen als:
    echo   %OUTPUT%
    if defined ROOMS_FLAG (
        echo Losse ruimte-PNG's staan in:
        echo   %IN_DIR%%IN_NAME%_schoon_ruimtes
    )
    echo Map wordt geopend...
    explorer /select,"%OUTPUT%"
) else (
    echo Er ging iets mis - zie de foutmelding hierboven.
)

echo.
pause
