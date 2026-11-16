@echo off
rem TJ Lecture watcher launcher (auto-grab). ASCII-only: cmd parses .cmd in OEM codepage.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "HERE=%~dp0"

if not exist "%HERE%.venv\Scripts\python.exe" (
  echo [x] .venv not found. Run setup.cmd first.
  exit /b 1
)

"%HERE%.venv\Scripts\python.exe" "%HERE%watch.py" %*
exit /b %ERRORLEVEL%
