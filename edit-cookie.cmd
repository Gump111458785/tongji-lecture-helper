@echo off
rem Open cookie.txt in Notepad. Paste the whole Cookie line from the browser, save, close.
chcp 65001 >nul
set "HERE=%~dp0"
if not exist "%HERE%cookie.txt" type nul > "%HERE%cookie.txt"
notepad "%HERE%cookie.txt"
