@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0启动企业工作台.ps1"
if errorlevel 1 pause
