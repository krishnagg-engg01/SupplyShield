@echo off
REM One-time setup: creates a virtual environment and installs dependencies.
where python >nul 2>nul || (echo Python 3.10+ is required. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH". & exit /b 1)
if not exist .venv ( python -m venv .venv || exit /b 1 )
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || exit /b 1
if not exist .env ( copy .env.example .env >nul & echo Created .env from .env.example. Demo mode needs no changes to it. For Exasol mode, fill in your Exasol connection details. )
echo.
echo Setup complete. Next: run  run_app.bat   - edit .env first only if you want Exasol mode.
