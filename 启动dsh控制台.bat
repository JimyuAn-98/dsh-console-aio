@echo off
rem dsh-console-aio launcher - double-click to open GUI (no console window)
rem 优先用 conda 的 console 环境(pythonw); 找不到则回退 base pythonw, 再回退 PATH pythonw。
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem ---- conda 完整路径(不依赖 PATH; 直接调 conda.exe run 拿 console 环境 pythonw) ----
if not defined CONDA_EXE set "CONDA_EXE=C:\ProgramData\miniconda3\Scripts\conda.exe"
if not defined PYW set "PYFILE=%TEMP%\dsh_console_pythonw.txt"

rem ---- 优先环境变量 PYW / 已解析 ----------------
if defined PYW goto :have_pyw

rem ---- 从 conda 的 console 环境解析 pythonw(同目录 python.exe 旁的 pythonw.exe) ----
if not exist "%CONDA_EXE%" goto :have_pyw
del "%PYFILE%" >nul 2>nul
"%CONDA_EXE%" run -n console python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" > "%PYFILE%" 2>nul
if not exist "%PYFILE%" goto :have_pyw
set /p PYW=<"%PYFILE%"
del "%PYFILE%" >nul 2>nul

:have_pyw
rem ---- 回退链: console 环境 pythonw -> base pythonw -> PATH pythonw ----
if defined PYW if exist "%PYW%" goto :launch
set "PYW=C:\ProgramData\miniconda3\pythonw.exe"
if exist "%PYW%" goto :launch
where pythonw >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python pythonw.exe not found. Install Miniconda with 'console' env, or set PYW.
    pause & exit /b 1
)
set "PYW=pythonw"

:launch
if not exist "%~dp0dsh-console-aio.py" (
    echo [ERROR] dsh-console-aio.py not found next to this launcher.
    pause & exit /b 1
)
start "" "%PYW%" "%~dp0dsh-console-aio.py"
exit /b 0
