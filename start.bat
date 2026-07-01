@echo off
chcp 65001 >nul
title A股分析系统
cd /d "%~dp0"

REM ── 检查服务是否已在运行 ──
curl -s -o nul http://localhost:5001/api/v3/health >nul 2>&1
if not errorlevel 1 (
    start http://localhost:5001
    echo 服务已在运行，已打开浏览器
    exit /b
)

REM ── 加载 .env ──
if exist .env (
    for /f "tokens=*" %%a in (.env) do set %%a
)

REM ── 数据目录 ──
if "%DATA_DIR%"=="" (
    set "DATA_DIR=%APPDATA%\Astock"
)
if not exist "%DATA_DIR%\duckdb\temp" mkdir "%DATA_DIR%\duckdb\temp"
if not exist "%DATA_DIR%\logs" mkdir "%DATA_DIR%\logs"

REM ── 数据库首次初始化 ──
set "SQLITE_DB=%DATA_DIR%\app.db"
set "DATABASE_URL=sqlite:///%SQLITE_DB:\=/%"
if not exist "%SQLITE_DB%" (
    echo [首次运行] 初始化数据库...
    python backend\run.py --init-db
)

REM ── 启动后端 ──
echo 正在启动 A股分析系统...
start "Astock Backend" /B python backend\run.py --port 5001
echo 启动中，请稍候...

REM ── 等待服务就绪（最多 30 秒）──
set count=0
:wait_loop
timeout /t 2 /nobreak >nul
curl -s -o nul http://localhost:5001/api/v3/health
if errorlevel 1 (
    set /a count+=1
    if !count! lss 15 goto wait_loop
    echo 服务启动超时，请检查日志
    pause
    exit /b 1
)

REM ── 打开浏览器 ──
start http://localhost:5001
echo 系统已就绪，请使用浏览器访问 http://localhost:5001
echo 关闭此窗口不会停止后端，请使用 stop.bat 停止
pause
