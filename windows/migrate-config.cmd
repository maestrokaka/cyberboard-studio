@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0resources\python\python.exe" -X utf8 "%~dp0resources\backend\migrate-config.py" %*
echo.
pause
