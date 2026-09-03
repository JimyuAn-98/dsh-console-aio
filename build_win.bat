@echo off
rem ---- Build dsh-console-aio: onefile exe (PyInstaller) + setup.exe (Inno Setup) ----
rem Prereq: conda env 'console' (python 3.12.9, pyside6 installed) + Inno Setup 6 (ISCC).
rem PySide6 的 Qt 库由 PyInstaller hooks 自动收集; 此处显式添加 QSS 主题/logo 资源 + exe 图标。

rem ---- conda 完整路径(不依赖 PATH; 直接调 conda.exe run 拿 console 环境 python, 无需 PowerShell) ----
if not defined CONDA_EXE set "CONDA_EXE=C:\ProgramData\miniconda3\Scripts\conda.exe"

rem ---- 优先用环境变量 PYTHON_EXE; 否则从 conda 的 console 环境解析 python ----
if defined PYTHON_EXE goto :have_python
if not exist "%CONDA_EXE%" (
    echo [ERROR] conda.exe not found: "%CONDA_EXE%"
    echo         Set CONDA_EXE or PYTHON_EXE, or install Miniconda.
    pause & exit /b 1
)
echo [0/2] Resolving console env python (conda run)...
set "PYFILE=%TEMP%\dsh_console_python.txt"
del "%PYFILE%" >nul 2>nul
"%CONDA_EXE%" run -n console python -c "import sys;print(sys.executable)" > "%PYFILE%" 2>nul
if not exist "%PYFILE%" (
    echo [ERROR] conda run failed to resolve console env python.
    pause & exit /b 1
)
set /p PYTHON_EXE=<"%PYFILE%"
del "%PYFILE%" >nul 2>nul
:have_python
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python not found: "%PYTHON_EXE%"
    echo         Ensure conda env 'console' exists (python 3.12.9^) or set PYTHON_EXE.
    pause & exit /b 1
)
echo Python: "%PYTHON_EXE%"

setlocal
cd /d "%~dp0"

rem ---- conda 环境本地打包: 环境的 Library\bin 须在 PATH, PyInstaller 才会把 ffi.dll 等
rem ---- 运行时 DLL 收进包, 否则冻结 exe 启动即 ImportError(_ctypes)。CI 的 pip 版
rem ---- python 无此问题; 此处从解析到的 python 路径推导环境根, 脚本自洽不依赖文档记忆。
for %%F in ("%PYTHON_EXE%") do set "ENV_ROOT=%%~dpF"
set "PATH=%ENV_ROOT%Library\bin;%PATH%"

echo [1/2] PyInstaller onefile build (PySide6)...
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name dsh-console-aio ^
  --icon logo.ico ^
  --hidden-import core --hidden-import core.tunnel_mgr ^
  --hidden-import ui.monitor --hidden-import ui.pages_overview ^
  --hidden-import ui.pages_tunnels --hidden-import ui.dialog_tunnel_wizard --hidden-import ui.pages_dsh ^
  --hidden-import ui.pages_sessions --hidden-import ui.pages_agents ^
  --hidden-import ui.pages_profiles --hidden-import ui.pages_plugins ^
  --hidden-import ui.pages_taskboard --hidden-import ui.pages_usage ^
  --hidden-import ui.pages_llm --hidden-import ui.pages_ops ^
  --hidden-import ui.pages_keys --hidden-import ui.pages_version ^
  --hidden-import ui.pages_deployments --hidden-import ui.pages_logs ^
  --hidden-import ui.pages_settings --hidden-import ui.pages_theme ^
  --add-data "ui/theme.qss;ui" ^
  --add-data "logo.png;." ^
  --add-data "RELEASE_NOTES.md;." ^
  dsh-console-aio.py
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    pause & exit /b 1
)
echo Build OK: dist\dsh-console-aio.exe

echo [2/2] Inno Setup installer...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo [WARN] ISCC.exe not found - installer skipped. Install Inno Setup 6.
) else (
    "%ISCC%" installer\installer.iss
    if errorlevel 1 (
        echo [ERROR] Installer build failed.
        pause & exit /b 1
    )
    echo Installer OK: dist\dsh-console-aio-setup-*.exe
)
pause