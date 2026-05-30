@echo off
cd /d "%~dp0"
title CARdle Unified Server

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment .venv not found!
    pause
    exit /b 1
)

.venv\Scripts\python.exe tools\runner.py
pause
