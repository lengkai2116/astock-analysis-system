@echo off
chcp 65001 >nul
title A股分析系统

cd /d "%~dp0"

REM ============================================
REM 无 Docker 启动脚本（Windows / macOS / Linux）
REM ============================================
REM 需要: Python 3.10+
REM 可选: Node.js 18+（首次构建前端需要）
REM
REM 双击即可完成：环境检查 → 依赖安装 → 服务启动 → 打开浏览器
REM ============================================

echo ╔═══════════════════════════════════════╗
echo ║       A股股票分析决策支持系统           ║
echo ║       双击即用 · 无需 Docker           ║
echo ╚═══════════════════════════════════════╝
echo.

REM ---- 1. 检查 Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请安装 Python 3.10+
    echo 下载: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM ---- 2. 创建 .env（首次） ----
if not exist ".env" (
    echo [首次] 正在从模板创建 .env 配置文件...
    copy .env.example .env >nul
    echo.
    echo ⚠ 请打开 .env 文件，填入以下信息：
    echo    - TUSHARE_TOKEN=你的 Tushare Pro Token
    echo    - DEEPSEEK_API_KEY=你的 DeepSeek API Key（如不使用 AI 可跳过）
    echo    - SECRET_KEY=任意随机字符串
    echo.
    pause
    start notepad .env
    echo 填写完成后按任意键继续...
    pause >nul
)

REM ---- 3. 设置关键路径（跨平台兼容） ----
REM DATA_DIR 指向项目根目录下的 data/ 文件夹
set "DATA_DIR=%CD%\data"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

REM ---- 4. 构建前端（首次或代码更新后） ----
if not exist "frontend\vue-project\dist\index.html" (
    echo [信息] 首次启动，正在构建前端...
    cd frontend\vue-project
    
    if not exist "node_modules" (
        where node >nul 2>&1
        if %errorlevel% neq 0 (
            echo [警告] 未找到 Node.js，无法构建前端
            echo 请安装 Node.js 18+ 后重试
            echo 下载: https://nodejs.org/
            pause
            exit /b 1
        )
        echo [信息] 安装前端依赖...
        call npm install
    )
    
    call npm run build
    if %errorlevel% neq 0 (
        echo [错误] 前端构建失败
        pause
        exit /b 1
    )
    cd /d "%~dp0"
    echo [完成] 前端构建完成
)

REM ---- 5. 安装后端依赖（首次） ----
if not exist "backend\.venv" (
    echo [信息] 首次启动，正在创建 Python 虚拟环境...
    cd backend
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [信息] 安装后端依赖...
    call .venv\Scripts\pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 安装后端依赖失败
        pause
        exit /b 1
    )
    cd /d "%~dp0"
    echo [完成] 后端依赖安装完成
)

REM ---- 6. 检查服务是否已在运行 ----
curl -s -o nul http://localhost:5001/api/v3/health 2>nul
if %errorlevel% equ 0 (
    echo [信息] 服务已在运行
    start http://localhost:5001
    exit /b 0
)

REM ---- 7. 启动后端 ----
echo [启动] 正在启动后端服务（端口 5001）...
echo [信息] 首次启动需创建数据库，请耐心等待
echo.

REM 启动后端（在后台窗口运行）
start "A股系统后端" /B /MIN cmd /c "cd /d "%~dp0\backend" && set DATA_DIR=%CD%\data && .venv\Scripts\python run.py --port 5001"

REM ---- 8. 等待服务就绪 ----
echo [等待] 检测服务状态...
setlocal EnableDelayedExpansion
set RETRIES=0
:wait_loop
timeout /t 2 /nobreak >nul
curl -s -o nul http://localhost:5001/api/v3/health 2>nul
if !errorlevel! equ 0 (
    echo.
    echo ✅ 服务已就绪！
    echo ────────────────────────────
    echo   访问地址: http://localhost:5001
    echo   停止服务: 双击 stop.bat
    echo ────────────────────────────
    echo.
    start http://localhost:5001
    goto end
)
set /a RETRIES=RETRIES+1
if !RETRIES! lss 30 goto wait_loop

echo [错误] 服务启动超时（60秒），请检查:
echo   1. backend/logs/ 下的日志文件
echo   2. 端口 5001 是否被其他程序占用
echo   3. 手动运行: cd backend ^& .venv\Scripts\python run.py --port 5001
pause

:end
endlocal
