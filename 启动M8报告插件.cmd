@echo off
chcp 65001 >nul
set "M8_ENTRY=%~dp0nxdrp\checkers\m8_report\start_m8.ps1"
if not exist "%M8_ENTRY%" set "M8_ENTRY=%~dp0start_m8.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%M8_ENTRY%" %*
set "M8_EXIT=%ERRORLEVEL%"
if not "%M8_EXIT%"=="0" echo M8 launch failed. Please keep this window open and share the error above.
if not defined M8_NO_PAUSE pause
exit /b %M8_EXIT%
