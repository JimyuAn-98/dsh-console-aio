@echo off
rem dsh-tunnel-console launcher - double-click to open GUI (no command needed)
rem Uses conda base pythonw (no console window); falls back to PATH pythonw.
setlocal
cd /d "%~dp0"

rem ---- EDIT HERE: your own Python path if needed ----
set "PYW=C:\ProgramData\miniconda3\pythonw.exe"
rem ---------------------------------------------------

if not exist "%PYW%" (
    where pythonw >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python pythonw.exe not found.
        echo Install Miniconda, or edit PYW path at top of this file.
        pause
        exit /b 1
    )
    set "PYW=pythonw"
)

if not exist "%~dp0dsh-tunnel-console.py" (
    echo [ERROR] dsh-tunnel-console.py not found next to this launcher.
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0dsh-tunnel-console.py"
exit /b 0
