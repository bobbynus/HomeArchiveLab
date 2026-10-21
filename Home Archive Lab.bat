@echo off
rem First run: creates a virtual environment and installs dependencies, then starts the app.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up Home Archive Lab...
    py -3 -m venv .venv || python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\pip.exe" install -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" run.pyw
