@echo off
call .venv\Scripts\activate.bat || (echo Run setup_windows.bat first. & exit /b 1)
start "" http://127.0.0.1:5000
python app.py
