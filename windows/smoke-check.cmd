@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Cyberboard Studio runtime checks - no USB access
"%~dp0resources\python\python.exe" -X utf8 -m cyberboard.cli --version
if errorlevel 1 goto failed
"%~dp0resources\python\python.exe" -X utf8 -m cyberboard.cli store --selftest
if errorlevel 1 goto failed
"%~dp0resources\python\python.exe" -X utf8 -c "from zoneinfo import ZoneInfo; print(ZoneInfo('Asia/Shanghai'))"
if errorlevel 1 goto failed
echo All offline runtime checks passed.
goto done
:failed
echo A runtime check failed. Keep the complete application folder and read 使用说明.txt.
:done
echo.
pause
