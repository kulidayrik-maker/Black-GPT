@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 blackgpt_agent.py
if errorlevel 1 python blackgpt_agent.py
pause
