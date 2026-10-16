@echo off
cd /d "%~dp0"
if exist "dist\ATV subshift\ATV subshift.exe" (
    start "" "dist\ATV subshift\ATV subshift.exe"
) else (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
)
