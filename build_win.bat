@echo off
rem ---- Build dsh-console-aio: onefile exe (PyInstaller) + setup.exe (Inno Setup) ----
rem Prereq: pip install pyinstaller pyside6 ; Inno Setup 6 installed (ISCC in PATH or default dir)
rem PySide6 的 Qt 库由 PyInstaller hooks 自动收集; 此处仅显式添加 QSS 主题资源。
setlocal
cd /d "%~dp0"

echo [1/2] PyInstaller onefile build (PySide6)...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name dsh-console-aio ^
  --hidden-import dsh_data --hidden-import tunnel_mgr ^
  --hidden-import pyside.dialogs ^
  --hidden-import pyside.pages_sessions --hidden-import pyside.pages_agents ^
  --hidden-import pyside.pages_profiles --hidden-import pyside.pages_plugins ^
  --hidden-import pyside.pages_taskboard --hidden-import pyside.pages_usage ^
  --hidden-import pyside.pages_llm --hidden-import pyside.pages_ops ^
  --hidden-import pyside.pages_keys --hidden-import pyside.pages_version ^
  --hidden-import pyside.pages_deployments ^
  --add-data "ui/theme.qss;ui" ^
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
    "%ISCC%" installer.iss
    if errorlevel 1 (
        echo [ERROR] Installer build failed.
        pause & exit /b 1
    )
    echo Installer OK: dist\dsh-console-aio-setup-*.exe
)
pause
