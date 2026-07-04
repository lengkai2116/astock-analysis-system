#!/bin/bash
cd "/Users/kalence/Desktop/01-A股股票分析系统/frontend/vue-project"
clear
cat << "BANNER"
╔═══════════════════════════════════════════╗
║        ② 前端 Vite  端口 9000            ║
║                                           ║
║  ▶ 修改 .vue/.ts 文件自动热更新           ║
║  ▶ Ctrl+C 停止服务                        ║
║  ▶ 关闭窗口即可退出                       ║
╚═══════════════════════════════════════════╝
BANNER
echo ""
exec npx vite --port 9000
