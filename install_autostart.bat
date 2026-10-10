@echo off
REM Registers Project Zero to start when you log in (runs minimized, no browser popup). Free: uses Windows Task Scheduler.
cd /d "%~dp0"
schtasks /Create /TN "ProjectZero" /TR "cmd /c cd /d \"%CD%\" && python run.py start --no-browser" /SC ONLOGON /RL LIMITED /F
pause
