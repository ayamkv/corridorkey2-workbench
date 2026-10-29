@echo off
rem CorridorKey2 Workbench launcher. Drag clips or image-sequence folders onto this file to import them.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo The app venv is missing. See README.md ^> Setup.
    pause
    exit /b 1
)
rem keep temp files next to the app (the system drive may be nearly full)
if not exist ".cache\tmp" mkdir ".cache\tmp"
set "TMP=%~dp0.cache\tmp"
set "TEMP=%~dp0.cache\tmp"
start "" ".venv\Scripts\pythonw.exe" -m ckapp %*
