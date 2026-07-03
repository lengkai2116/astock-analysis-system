#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 网络环境诊断脚本 — 适用于 A 股股票分析系统
#
# 诊断项：
#   1. Shell 中的 HTTP_PROXY / ALL_PROXY 环境变量来源
#   2. 原始 Python 环境是否能直连东方财富 API
#   3. AKShare 是否可正常调用（需 Django venv 中安装过 akshare）
#   4. PySocks 是否已安装
#   5. 推荐的修复方案
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/backend/.venv"
PYTHON="$VENV_DIR/bin/python3"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo "═══════════════════════════════════════════════════════"
echo " 🔍  A股股票分析系统 — 网络环境诊断"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── 步骤 1：检查环境变量来源 ──
echo -e "${CYAN}[1/6] 正在定位 HTTP_PROXY 环境变量来源...${NC}"

# 检查当前 shell 中代理变量
for var in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
    val="${!var}"
    if [ -n "$val" ]; then
        echo -e "  ${YELLOW}$var = ${val:0:80}${NC}"
    fi
done

# 如果设置了代理变量，找来源
if [ -n "$HTTP_PROXY" ] || [ -n "$http_proxy" ]; then
    echo ""
    echo "  在以下文件中查找代理配置："
    for rc in ~/.zshrc ~/.zshenv ~/.zprofile ~/.bash_profile ~/.bashrc ~/.profile; do
        if [ -f "$rc" ]; then
            matches=$(grep -n -i "proxy\|ALL_PROXY\|49577\|49578" "$rc" 2>/dev/null)
            if [ -n "$matches" ]; then
                echo -e "  ${YELLOW}→ 找到潜在配置: $rc${NC}"
                echo "$matches" | while read line; do
                    echo "    $line"
                done
            fi
        done
    done

    # 检查 launchd plist
    for plist in ~/Library/LaunchAgents/*.plist; do
        if [ -f "$plist" ]; then
            matches=$(grep -l "proxy\|49577\|49578" "$plist" 2>/dev/null)
            if [ -n "$matches" ]; then
                echo -e "  ${YELLOW}→ 找到 LaunchAgent 配置: $plist${NC}"
            fi
        fi 2>/dev/null
    done
else
    echo -e "  ${GREEN}无代理环境变量（干净环境）${NC}"
fi

# ── 步骤 2：DNS 解析测试 ──
echo ""
echo -e "${CYAN}[2/6] DNS 解析测试...${NC}"
for host in push2.eastmoney.com datacenter.eastmoney.com quote.eastmoney.com; do
    result=$(dig +short "$host" 2>/dev/null || nslookup "$host" 2>/dev/null | grep -A1 "Name" | tail -1)
    if [ -n "$result" ]; then
        echo -e "  ${GREEN}$host → $result${NC}"
    else
        result=$(host "$host" 2>/dev/null | head -1)
        if [ -n "$result" ]; then
            echo -e "  ${GREEN}$host → $result${NC}"
        else
            echo -e "  ${RED}$host → DNS 解析失败${NC}"
        fi
    fi
done

# ── 步骤 3：curl 直连测试（不带任何代理） ──
echo ""
echo -e "${CYAN}[3/6] curl 直连测试（--noproxy 强制直连）...${NC}"
for url in \
    "https://push2.eastmoney.com/api/qt/clist/get?cb=jQuery&fid=f3&pn=1&np=1&pz=5&po=1&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f2,f3,f62,f184,f66,f69" \
    "https://datacenter.eastmoney.com/api/data/v1/get?reportName=RPT_MUTUAL_DEAL_STOCK_HISTORY&columns=ALL" \
    "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f12,f14&secids=1.000001,0.000001"; do
    status=$(curl -s --noproxy '*' -o /dev/null -w "%{http_code}" --connect-timeout 5 "$url" 2>/dev/null)
    if [ "$status" = "200" ]; then
        echo -e "  ${GREEN}[$status] ${url:0:80}...${NC}"
    else
        echo -e "  ${RED}[$status] ${url:0:80}...${NC} (失败)"
    fi
done

# ── 步骤 4：Python 环境检查 ──
echo ""
echo -e "${CYAN}[4/6] Python 环境检查...${NC}"

# 检查 venv 是否存在
if [ -f "$PYTHON" ]; then
    echo -e "  ${GREEN}✓ venv 存在: $VENV_DIR${NC}"

    # PySocks 检查
    if "$PYTHON" -c "import socks; print('PySocks版本:', socks.__version__)" 2>/dev/null; then
        echo -e "  ${GREEN}✓ PySocks 已安装${NC}"
    else
        echo -e "  ${YELLOW}✗ PySocks 未安装 → SOCKS5 代理会失败${NC}"
    fi

    # requests 检查
    if "$PYTHON" -c "import requests; print('requests版本:', requests.__version__)" 2>/dev/null; then
        echo -e "  ${GREEN}✓ requests 已安装${NC}"
    else
        echo -e "  ${RED}✗ requests 未安装${NC}"
    fi

    # AKShare 检查
    if "$PYTHON" -c "import akshare; print('akshare版本:', akshare.__version__)" 2>/dev/null; then
        echo -e "  ${GREEN}✓ AKShare 已安装${NC}"
    else
        echo -e "  ${YELLOW}✗ AKShare 未安装${NC}"
    fi
else
    echo -e "  ${RED}✗ venv Python 不存在: $PYTHON${NC}"
    # 尝试找到系统中其他 Python
    ALT_PY=$(which python3 2>/dev/null)
    if [ -n "$ALT_PY" ]; then
        echo -e "  ${YELLOW}  使用系统 $ALT_PY${NC}"
        PYTHON="$ALT_PY"
    fi
fi

# ── 步骤 5：Python requests 真实环境测试（绕开 env 代理变量） ──
echo ""
echo -e "${CYAN}[5/6] Python 直连测试（完全清除代理环境变量）...${NC}"

TEST_SCRIPT=$(cat << 'PYEOF'
import os, sys, json

# 彻底清除所有代理变量
for k in list(os.environ.keys()):
    if k.lower().endswith('proxy') or k.lower().endswith('_proxy'):
        del os.environ[k]

print("=== 清理后环境变量 ===")
for k in sorted(os.environ.keys()):
    if k.lower() == 'home' or k.lower() == 'path':
        continue
    if any(x in k.lower() for x in ['proxy']):
        print(f"  !! 残留: {k}={os.environ[k][:60]}")

print("=== 测试 1: requests.get(push2.eastmoney.com) ===")
import requests
try:
    r = requests.get(
        "https://push2.eastmoney.com/api/qt/clist/get",
        params={"cb": "jQuery", "fid": "f3", "pn": "1", "np": "1", "pz": "5",
                "po": "1", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f14,f2,f3,f62,f184,f66,f69"},
        timeout=5,
        proxies={"http": None, "https": None}  # 显式禁用代理
    )
    print(f"  ✅ 成功! status={r.status_code}, 前100字节: {r.text[:100]}")
except Exception as e:
    print(f"  ❌ 失败: {type(e).__name__}: {str(e)[:150]}")

print("\n=== 测试 2: requests.get(datacenter.eastmoney.com) ===")
try:
    r = requests.get(
        "https://datacenter.eastmoney.com/api/data/v1/get",
        params={"reportName": "RPT_MUTUAL_DEAL_STOCK_HISTORY", "columns": "ALL"},
        timeout=5,
        proxies={"http": None, "https": None}
    )
    print(f"  ✅ 成功! status={r.status_code}, 前100字节: {r.text[:100]}")
except Exception as e:
    print(f"  ❌ 失败: {type(e).__name__}: {str(e)[:150]}")

print("\n=== 测试 3: akshare 调用（如已安装） ===")
try:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    print(f"  ✅ AKShare stock_zh_a_spot_em 成功! {len(df)} 行, 列: {list(df.columns[:5])}")
except ImportError:
    print("  ⏭  AKShare 未安装，跳过")
except Exception as e:
    print(f"  ❌ AKShare 失败: {type(e).__name__}: {str(e)[:150]}")
    if 'ProxyError' in type(e).__name__:
        print(f"    检测到代理错误！请在 shell 配置中清除所有 HTTP_PROXY/ALL_PROXY 环境变量")
PYEOF
)

# 使用 env -i 启动完全干净的 python 进程
if [ -f "$VENV_DIR/bin/python3" ]; then
    env -i HOME="$HOME" PATH="$VENV_DIR/bin:/usr/bin:/bin" "$PYTHON" -c "$TEST_SCRIPT"
else
    python3 -c "$TEST_SCRIPT"
fi

# ── 步骤 6：修复建议 ──
echo ""
echo -e "${CYAN}[6/6] 诊断结论与修复建议${NC}"

echo ""
echo "————————————————— 诊断结果 —————————————————"
if [ -n "$HTTP_PROXY" ] || [ -n "$ALL_PROXY" ]; then
    echo -e "  ${YELLOW}⚠ 检测到代理环境变量${NC}"
    echo "    来源: 请查看上方步骤1的排查结果"
    echo "    影响: Python requests 库会自动使用这些代理设置"
    echo "    ALL_PROXY=socks5h://... 会导致 'InvalidSchema: Missing dependencies for SOCKS support'"
    echo "    HTTP_PROXY=http://... 会导致 ProxyError（如果代理服务器已停止）"
    echo ""
    echo -e "  ${GREEN}推荐修复方案 A — 移除环境变量（一劳永逸）：${NC}"
    echo "    1. 在 ~/.zshrc 或 ~/.zshenv 中找到并注释掉以下行："
    echo "       # export HTTP_PROXY=..."
    echo "       # export HTTPS_PROXY=..."
    echo "       # export ALL_PROXY=..."
    echo "    2. 执行 source ~/.zshrc 重新加载"
    echo "    3. 重新启动系统"
    echo ""
    echo -e "  ${GREEN}推荐修复方案 B — 安装 PySocks（代码兼容）：${NC}"
    echo "    $VENV_DIR/bin/pip install PySocks"
    echo "    这样 SOCKS5 代理路径也能工作"
    echo ""
    echo -e "  ${GREEN}推荐修复方案 C — 代码层面免疫（无需改 shell）：${NC}"
    echo "    在 akshare_provider.py 中设置 trust_env=False"
    echo "    session = requests.Session()"
    echo "    session.trust_env = False  # 忽略环境变量中的代理"
    echo ""
else
    echo -e "  ${GREEN}✓ 无代理环境变量${NC}"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo " 诊断完成"
echo "═══════════════════════════════════════════════════════"
echo ""
