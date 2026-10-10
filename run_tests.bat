@echo off
cd /d "%~dp0"
python run.py selftest
python -m unittest discover -s tests -t .
pause
