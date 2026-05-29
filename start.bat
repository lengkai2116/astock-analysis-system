@echo off
chcp 65001 >nul
title A股分析系统

echo ============================================
echo   A股分析系统 - 启动中...
echo ============================================
echo.

cd /d "%~dp0"

REM 检查 Docker 是否运行
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker 未运行，请先启动 Docker Desktop
    echo.
    pause
    exit /b 1
)

REM 启动服务
echo [1/2] 启动容器...
docker compose up -d --build

REM 等待就绪
echo [2/2] 等待服务就绪...
setlocal enabledelayedexpansion
for /l %%i in (1,1,30) do (
    curl -s -o nul -w "%%{http_code}" http://localhost:9000/health 2>nul | find "200" >nul
    if !errorlevel! equ 0 (
        echo   ✅ 前端就绪 ^(http://localhost:9000^)
        goto :OPEN
    )
    timeout /t 1 /nobreak >nul
)
:OPEN

echo.
echo ✅ 启动完成！正在打开浏览器...
start http://localhost:9000

echo.
echo 关闭此窗口即可停止（后台服务继续运行）
echo 如需停止服务: docker compose down
echo.
pause
