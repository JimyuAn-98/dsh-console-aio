@echo off
rem ---- Build a single-file Windows exe with PyInstaller ----
rem Prereq: pip install pyinstaller   (into your Python env)
setlocal
cd /d "%~dp0"

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name dsh-console-aio ^
  --add-data "config.example.json;." ^
  dsh-console-aio.py

if errorlevel 1 (
    echo [ERROR] Build failed. Make sure 'pip install pyinstaller' ran.
    pause
    exit /b 1
)
echo.
echo Build OK: dist\dsh-console-aio.exe
echo Note: first run on another machine will use built-in defaults;
echo       copy config.example.json to config.json and edit it.
pause