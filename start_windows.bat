@echo off
chcp 65001 > nul
title NetScope Studio v4 - TCP HTTP Server
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py server.py
) else (
  python server.py
)
pause
