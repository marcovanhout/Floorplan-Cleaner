@echo off
setlocal enabledelayedexpansion
title Plattegrond Schoonmaker - Installatie

echo ============================================================
echo   Plattegrond Schoonmaker - eenmalige installatie
echo ============================================================
echo Dit installeert automatisch: Python, Tesseract-OCR, en de
echo benodigde Python-onderdelen. Dit hoeft maar 1x per pc.
echo.
echo Er kan een Windows-beveiligingsvenster verschijnen
echo ("Wil je toestaan dat deze app wijzigingen aanbrengt?").
echo Klik dan op "Ja".
echo.
pause

REM ------------------------------------------------------------
REM  Check of winget beschikbaar is (standaard aanwezig op
REM  Windows 10 2004+ en Windows 11 via "App Installer")
REM ------------------------------------------------------------
where winget >nul 2>nul
if errorlevel 1 (
    echo.
    echo FOUT: winget is niet gevonden op dit systeem.
    echo winget zit in "App Installer", te vinden in de Microsoft Store:
    echo   https://apps.microsoft.com/detail/9nblggh4nns1
    echo Installeer dat eerst en start dit bestand daarna opnieuw.
    echo.
    pause
    exit /b 1
)

REM ------------------------------------------------------------
REM  Python
REM ------------------------------------------------------------
echo.
echo --- Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo Python niet gevonden, wordt geinstalleerd...
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    echo.
    echo Python is geinstalleerd. Dit venster wordt zo afgesloten,
    echo start dit bat-bestand daarna nog EEN KEER opnieuw
    echo ^(Windows moet de PATH-instelling eerst verversen^).
    echo.
    pause
    exit /b 0
) else (
    echo Python is al geinstalleerd - overgeslagen.
)

REM ------------------------------------------------------------
REM  Tesseract-OCR
REM ------------------------------------------------------------
echo.
echo --- Tesseract-OCR ---
where tesseract >nul 2>nul
if errorlevel 1 (
    echo Tesseract-OCR niet gevonden, wordt geinstalleerd...
    winget install -e --id UB-Mannheim.TesseractOCR --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo Kon Tesseract niet automatisch installeren.
        echo Dit is alleen nodig voor PDF's ZONDER CAD-lagen ^(fallback-methode^).
        echo Handmatig te installeren via:
        echo   https://github.com/UB-Mannheim/tesseract/wiki
        echo Ga verder met de rest van de installatie.
        echo.
        pause
    )
) else (
    echo Tesseract-OCR is al geinstalleerd - overgeslagen.
)

REM ------------------------------------------------------------
REM  Python-pakketten
REM ------------------------------------------------------------
echo.
echo --- Python-pakketten ---
python -m pip install --upgrade pip
python -m pip install pymupdf pillow numpy matplotlib pytesseract scipy

echo.
if errorlevel 1 (
    echo Er ging iets mis bij het installeren van de Python-pakketten.
    echo Controleer de foutmelding hierboven.
) else (
    echo ============================================================
    echo   Installatie voltooid!
    echo ============================================================
    echo Je kunt nu Plattegrond_Schoonmaker.bat gebruiken: sleep een
    echo PDF erbovenop, of dubbelklik en kies een PDF.
)

echo.
pause
