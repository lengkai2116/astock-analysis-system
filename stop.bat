@echo off
chcp 65001 >nul
title A股分析系统 - 停止

cd /d "%~dp0"

echo 正在停止后端服务...
taskkill /f /fi "WINDOWTITLE eq A股分析系统后端*" 2>nul
echo 已停止

REM 可选: 查找占用 5001 端口的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001"') do (
    taskkill /f /pid %%a 2>nul
)

echo.
echo 服务已全部停止
timeout /t 2 /nobreak >nul
