@echo off
chcp 65001 > nul
title GameVault 1-Click Release Tool

cd /d "%~dp0"

echo ===================================================
echo   🎮 GameVault - One-Click Auto Release Tool
echo ===================================================
echo.
echo กำลังเปิดหน้าต่างเครื่องมือ Release...
start "" pythonw release_gui.py
if errorlevel 1 (
    python release_gui.py
)
exit
