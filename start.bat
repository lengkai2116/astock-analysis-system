@echo off
chcp 65001 >nul
title A股分析系统

cd /d "%~dp0"

REM 检查服务是否已在运行
curl -s -o nul http://localhost:9000/health 2>nul
if %errorlevel% equ 0 (
    start http://localhost:9000
    exit /b
)

REM 首次启动
echo 首次启动，正在构建容器...
docker compose up -d --build

echo 正在打开浏览器...
start http://localhost:9000
