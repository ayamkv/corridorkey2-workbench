@echo off
rem CorridorKey2 Workbench setup: installs everything into this folder. Safe to run again.
rem Options: -Weights download ^| -Weights "D:\path\to\weights"   -Yes   -NoShortcuts
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\packaging\setup.ps1" -Root "%~dp0." %*
echo.
pause
