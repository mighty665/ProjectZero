@echo off
cd /d "%~dp0"
where python >/dev/null 2>/dev/null || (echo Python was not found. Install it free from https://www.python.org/downloads/ and tick "Add python.exe to PATH". & pause & exit /b 1)
python run.py start
pause
