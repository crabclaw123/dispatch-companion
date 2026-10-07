@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install "PyJWT[crypto]>=2.8,<3"
if errorlevel 1 goto done
.venv\Scripts\python.exe plus_test.py
:done
pause
