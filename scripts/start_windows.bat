@echo off
rem Double-click this file to run JARVIS on this PC.
rem Everything else lives in start_windows.ps1 next to it.
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_windows.ps1" %*
if errorlevel 1 pause
endlocal
