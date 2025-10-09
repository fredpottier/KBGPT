@echo off
REM Script Windows pour lancer la revue nocturne
REM Usage: run_nightly_review.cmd [OPTIONS]

echo.
echo ========================================
echo   REVUE NOCTURNE SAP KB
echo ========================================
echo.

REM Vérifier que Python est installé
python --version >nul 2>&1
if errorlevel 1 (
    echo ERREUR: Python n'est pas installé ou pas dans le PATH
    pause
    exit /b 1
)

REM Aller à la racine du projet
cd /d "%~dp0\.."

REM Lancer la revue avec les arguments passés
python scripts\nightly_review.py %*

echo.
echo ========================================
echo   REVUE TERMINEE
echo ========================================
echo.

pause
