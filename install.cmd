@echo off
rem Sets Regista up on this PC. Double-click this file: it runs install.ps1, which says what it does
rem and asks before downloading anything.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
