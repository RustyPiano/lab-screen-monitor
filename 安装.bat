@echo off
chcp 65001 >nul 2>&1
powershell -ExecutionPolicy Bypass -NoLogo -File "%~dp0scripts\windows\setup.ps1"
pause
