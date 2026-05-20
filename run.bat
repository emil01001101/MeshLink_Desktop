@echo off
REM ============================================================
REM MeshLink Desktop - launcher Windows
REM Verifica Python, instaleaza dependinte daca lipsesc, ruleaza
REM ============================================================

setlocal
cd /d "%~dp0"

REM Verifica daca folderul "app" exista in directorul curent
if not exist "app\" (
    echo.
    echo ========================================================
    echo   EROARE: folderul 'app\' nu exista in:
    echo   %CD%
    echo ========================================================
    echo.
    echo Probabil ai extras doar main.py din ZIP.
    echo Te rog extrage INTREAGA arhiva, apoi ruleaza din nou.
    echo.
    pause
    exit /b 1
)

REM Verifica Python disponibil
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo EROARE: 'python' nu este in PATH.
    echo Instaleaza Python 3.10+ de pe https://www.python.org/
    echo si bifeaza "Add Python to PATH" la instalare.
    echo.
    pause
    exit /b 1
)

REM Verifica daca PySide6 e instalat. Daca nu, instaleaza dependintele.
python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Prima rulare: instalez dependintele Python...
    echo Va dura ~1-2 minute pe prima rulare.
    echo.
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo EROARE la instalarea dependintelor.
        pause
        exit /b 1
    )
)

REM Ruleaza aplicatia
python main.py
if errorlevel 1 (
    echo.
    echo Aplicatia s-a terminat cu eroare. Detalii mai sus.
    echo Log complet in: %USERPROFILE%\meshlink_desktop_logs\
    pause
)

endlocal
