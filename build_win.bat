@echo off
rem ---- Build dsh-console-aio: onefile exe (PyInstaller) + setup.exe (Inno Setup) ----
rem Prereq: pip install pyinstaller; Inno Setup 6 installed (ISCC in PATH or default dir)
setlocal
cd /d "%~dp0"

echo [1/2] PyInstaller onefile build...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name dsh-console-aio ^
  --hidden-import mgmt_sessions --hidden-import mgmt_agents --hidden-import mgmt_profiles ^
  --hidden-import mgmt_plugins --hidden-import mgmt_taskboard --hidden-import mgmt_usage ^
  --hidden-import mgmt_llm --hidden-import mgmt_theme --hidden-import mgmt_ops --hidden-import mgmt_version ^
  --add-data "RELEASE_NOTES.md;." ^
  --add-binary "%CONDA_PREFIX%\Library\bin\tcl86t.dll;." ^
  --add-binary "%CONDA_PREFIX%\Library\bin\tk86t.dll;." ^
  --add-data "%CONDA_PREFIX%\Library\lib\tcl8.6;tcl8.6" ^
  --add-data "%CONDA_PREFIX%\Library\lib\tk8.6;tk8.6" ^
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