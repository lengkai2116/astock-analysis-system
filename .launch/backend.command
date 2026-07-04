#!/bin/bash
cd "/Users/kalence/Desktop/01-A股股票分析系统/backend"
export FLASK_ENV=development
clear
cat << "BANNER"
╔═══════════════════════════════════════════╗
║        ① 后端 Flask  端口 5001           ║
║                                           ║
║  ▶ 修改 .py 文件后自动重载                ║
║  ▶ Ctrl+C 停止服务                        ║
║  ▶ 关闭窗口即可退出                       ║
╚═══════════════════════════════════════════╝
BANNER
echo ""
exec "/Users/kalence/Desktop/01-A股股票分析系统/backend/.venv/bin/python" run.py --port 5001
