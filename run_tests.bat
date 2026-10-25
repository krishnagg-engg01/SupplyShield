@echo off
call .venv\Scripts\activate.bat || (echo Run setup_windows.bat first. & exit /b 1)
python -m unittest discover -s tests -v
