@echo off
title GameVault Launcher
cd /d "%~dp0"
if exist "GameVault.exe" (
    start "" "GameVault.exe"
    exit /b
)
python app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo GameVault closed or encountered an issue.
    pause
)
