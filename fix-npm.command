#!/bin/bash
# A股分析系统 - 修复 npm 缓存权限问题
# 双击此文件 → 修复 npm 因 root 缓存文件导致的 EPERM 错误
# 仅在 npm install 报 "root-owned files" / "EPERM" 错误时运行

cd "$(dirname "$0")" || exit 1

clear
echo "╔════════════════════════════════════════════╗"
echo "║      A股分析系统 · npm 缓存权限修复       ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# 检查 npm cache 问题
NPM_CACHE_DIR="$HOME/.npm"
if [ -d "$NPM_CACHE_DIR" ]; then
    ROOT_FILES=$(find "$NPM_CACHE_DIR" -user root 2>/dev/null | head -5)
    if [ -n "$ROOT_FILES" ]; then
        echo "🔧 发现 root 所属的缓存文件，正在修复..."
        echo "   执行: chown -R $(id -u):$(id -g) \"$NPM_CACHE_DIR\""
        chown -R "$(id -u):$(id -g)" "$NPM_CACHE_DIR" 2>/dev/null
        echo "✅ 缓存权限已修复"
    else
        echo "✅ npm 缓存权限正常，无需修复"
    fi
fi

# 清理不完整的 node_modules
NODE_MODULES_DIR="$PWD/frontend/vue-project/node_modules"
PACKAGE_LOCK="$PWD/frontend/vue-project/package-lock.json"
if [ -d "$NODE_MODULES_DIR" ]; then
    echo ""
    echo "🔧 清理旧的 node_modules（重新安装）..."
    rm -rf "$NODE_MODULES_DIR" 2>/dev/null
fi
if [ -f "$PACKAGE_LOCK" ]; then
    rm -f "$PACKAGE_LOCK" 2>/dev/null
fi

# 重新安装
echo ""
echo "⌛ 正在安装前端依赖（npm install）..."
echo "   耗时约 30-120 秒，请耐心等待..."
echo ""

cd "$PWD/frontend/vue-project" || exit 1
npm install 2>&1

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 前端依赖安装成功！"
    echo "   现在可以双击 start-dev.command 启动全栈服务了。"
else
    echo ""
    echo "❌ npm install 失败，可能是网络问题。请尝试："
    echo ""
    echo "   方式 1：开启 VPN 后再试"
    echo "   方式 2：切换到国内镜像"
    echo "      cd frontend/vue-project && npm install --registry=https://registry.npmmirror.com"
    echo "   方式 3：联系管理员检查网络配置"
fi

echo ""
echo "按 Enter 键退出..."
read -r
