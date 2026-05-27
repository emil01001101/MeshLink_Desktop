@echo off
REM ============================================================
REM  MeshLink Desktop - Standalone EXE Builder
REM
REM  Builds a single-file Windows executable (MeshLinkDesktop.exe)
REM  using PyInstaller. No Python installation is required to run
REM  the resulting .exe.
REM
REM  Output: dist\MeshLinkDesktop.exe
REM ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

title MeshLink Desktop - EXE Builder

echo ============================================================
echo   MeshLink Desktop - building standalone executable
echo ============================================================
echo.

REM --- Verify Python is available --------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 'python' was not found in your PATH.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         and tick "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo [INFO] Detected Python !PYVER!
echo.

REM --- Install runtime dependencies ------------------------------------
echo [SETUP] Ensuring application dependencies are installed...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install application dependencies.
    pause
    exit /b 1
)

REM --- Install PyInstaller (build tool) --------------------------------
echo.
echo [SETUP] Installing PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

REM --- Clean previous build artifacts ----------------------------------
echo.
echo [CLEAN] Removing previous build output...
if exist "build\"  rmdir /s /q "build"
if exist "dist\"   rmdir /s /q "dist"
if exist "MeshLinkDesktop.spec" del /q "MeshLinkDesktop.spec"

REM --- Build the single-file executable --------------------------------
echo.
echo [BUILD] Compiling MeshLinkDesktop.exe ^(this can take several minutes^)...
echo.

python -m PyInstaller ^
    --name "MeshLinkDesktop" ^
    --onefile ^
    --windowed ^
    --noconfirm ^
    --clean ^
    --add-data "app;app" ^
    --collect-all meshtastic ^
    --collect-submodules meshtastic ^
    --collect-all pubsub ^
    --collect-submodules google.protobuf ^
    --hidden-import PySide6.QtWebEngineWidgets ^
    --hidden-import PySide6.QtWebEngineCore ^
    --hidden-import pyqtgraph ^
    --hidden-import numpy ^
    --hidden-import serial ^
    --hidden-import serial.tools.list_ports ^
    --hidden-import bleak ^
    --hidden-import yaml ^
    --exclude-module tkinter ^
    --exclude-module pytest ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed. See the messages above.
    pause
    exit /b 1
)

REM --- Done ------------------------------------------------------------
echo.
echo ============================================================
echo   BUILD SUCCESSFUL
echo.
echo   Your executable is ready at:
echo       %CD%\dist\MeshLinkDesktop.exe
echo.
echo   You can distribute this single file - it does not require
echo   Python to be installed on the target machine.
echo ============================================================
echo.

REM --- Clean up intermediate build files (keep dist\) ------------------
if exist "build\" rmdir /s /q "build"
if exist "MeshLinkDesktop.spec" del /q "MeshLinkDesktop.spec"

pause
endlocal
exit /b 0
