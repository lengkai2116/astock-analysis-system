@echo off
chcp 65001 >nul
title A股分析系统 - 停止
cd /d "%~dp0"

echo 正在停止后端服务...

REM ── 优雅停止：发 SIGTERM 到 python run.py 进程 ──
taskkill /f /fi "IMAGENAME eq python.exe" /fi "WINDOWTITLE eq Astock Backend*" 2>nul

REM ── 备选：直接查找占用 5001 端口的进程 ──
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001"') do (
    taskkill /f /pid %%a 2>nul
)

echo 后端已停止
timeout /t 2 /nobreak >nul
