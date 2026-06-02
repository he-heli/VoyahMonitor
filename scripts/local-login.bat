@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

where python >nul 2>&1 || (
  echo Error: Python is not in PATH. Install Python 3.11+ and try again.
  exit /b 1
)

if not exist .venv (
  echo Creating virtual environment in .venv ...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

python -m pip install -q -U pip
python -m pip install -q -e ".[login]"
playwright install chromium

if not exist data mkdir data

echo Starting VOYAH login (session -^> data\session.json) ...
python scripts\local_login.py

echo.
echo Next steps:
echo   1. voyah-monitor inspect   # copy API paths into .env
echo   2. Copy .env and data\session.json to your VPS (see docs/DEPLOY.md)

endlocal
