@echo off
REM ============================================================
REM  MeshLink Desktop - Windows Launcher
REM  Checks Python, installs dependencies if missing, then runs.
REM ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

title MeshLink Desktop

echo ============================================================
echo   MeshLink Desktop - starting...
echo ============================================================
echo.

REM --- Verify the application folder is present -------------------------
if not exist "app\" (
    echo [ERROR] The 'app\' folder was not found in:
    echo         %CD%
    echo.
    echo It looks like only some files were extracted from the ZIP.
    echo Please extract the ENTIRE archive, then run this file again.
    echo.
    pause
    exit /b 1
)

if not exist "main.py" (
    echo [ERROR] 'main.py' was not found in:
    echo         %CD%
    echo.
    echo Please extract the ENTIRE archive, then run this file again.
    echo.
    pause
    exit /b 1
)

REM --- Verify Python is available --------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 'python' was not found in your PATH.
    echo.
    echo Please install Python 3.10 or newer from:
    echo         https://www.python.org/downloads/
    echo and tick "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM --- Show the detected Python version --------------------------------
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo [INFO] Detected Python !PYVER!
echo.

REM --- Check core dependency; install all if missing -------------------
python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo [SETUP] First run detected - installing Python dependencies.
    echo         This may take 1-2 minutes. Please wait...
    echo.
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies.
        echo         Check your internet connection and try again.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo [SETUP] Dependencies installed successfully.
    echo.
)

REM --- Launch the application ------------------------------------------
echo [INFO] Launching MeshLink Desktop...
echo.
python main.py
set "EXITCODE=%errorlevel%"

if not "%EXITCODE%"=="0" (
    echo.
    echo ============================================================
    echo   The application exited with an error ^(code %EXITCODE%^).
    echo   Details are shown above.
    echo   Full logs are saved in:
    echo   %USERPROFILE%\meshlink_desktop_logs\
    echo ============================================================
    echo.
    pause
)

endlocal
exit /b %EXITCODE%
