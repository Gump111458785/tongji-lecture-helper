@echo off
rem Tongji Lecture signup CLI launcher.
rem ASCII-only on purpose: cmd.exe parses .cmd files in the OEM codepage,
rem so UTF-8 Chinese comments break parsing. Chinese docs live in the .md guide.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "HERE=%~dp0"

if not exist "%HERE%.venv\Scripts\python.exe" (
  echo [x] .venv not found. Run setup.cmd first to install dependencies.
  exit /b 1
)

"%HERE%.venv\Scripts\python.exe" "%HERE%tjh.py" %*
exit /b %ERRORLEVEL%
