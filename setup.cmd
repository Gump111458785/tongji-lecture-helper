@echo off
rem Rebuild .venv and install dependencies. Needs internet access.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "HERE=%~dp0"
set "PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

if not exist "%PY%" (
  echo [!] Bundled python not found, falling back to python on PATH
  set "PY=python"
)

if not exist "%HERE%.venv\Scripts\python.exe" (
  echo [*] Creating virtual environment .venv
  "%PY%" -m venv "%HERE%.venv"
  if errorlevel 1 (
    echo [x] Failed to create .venv
    exit /b 1
  )
)

echo [*] Installing requests
"%HERE%.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-input --timeout 20 --retries 2 -q requests
if errorlevel 1 (
  echo [!] Default index failed, retrying with Tsinghua mirror
  "%HERE%.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-input --timeout 20 --retries 2 -q -i https://pypi.tuna.tsinghua.edu.cn/simple requests
)
if errorlevel 1 (
  echo [x] Dependency install failed, check your network
  exit /b 1
)

"%HERE%.venv\Scripts\python.exe" -c "import requests,sys;print('[ok] Python',sys.version.split()[0],'requests',requests.__version__)"
exit /b %ERRORLEVEL%
