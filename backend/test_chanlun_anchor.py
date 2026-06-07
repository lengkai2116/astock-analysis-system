"""
缠论策略锚定验证测试
1. 导入 SignalComputationService，对多只股票运行缠论分析
2. 输出全中文分析报告（分析报告 字段）
3. 验证缠论决策树逻辑是否正确
"""
import sys, os
import importlib.util
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault('FLASK_ENV', 'development')

# 先导入 chanlun_strategy（处理依赖导入问题）
import importlib
with open(os.path.join(os.path.dirname(__file__), "app/engine/framework/chanlun_strategy.py")) as f:
    content = f.read()

lines = content.split('\n')
stripped = []
for line in lines:
    if 'from .screener import DarwinRiskFilter as _RealDarwinRiskFilter' in line:
        continue
    if 'class DarwinRiskFilter(_RealDarwinRiskFilter):' in line:
        continue
    stripped.append(line)

result = '\n'.join(stripped)
cut_pos = result.find('class DarwinRiskFilter(')
if cut_pos > 0:
    result = result[:result.rfind('\n', 0, cut_pos)] + '\n'

tmp_path = '/tmp/_chanlun_test_only.py'
with open(tmp_path, 'w') as f:
    f.write(result)

spec = importlib.util.spec_from_file_location("_chanlun_test_only", tmp_path)
chanlun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chanlun)

ChanlunAnalyzer = chanlun.ChanlunAnalyzer
print("✓ ChanlunAnalyzer 导入成功")
print()

# 测试数据：使用模拟数据运行分析
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_test_data(days=500, start_price=25.0, volatility=0.03):
    """生成模拟日线数据用于验证分析逻辑"""
    np.random.seed(42)
    dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days, 0, -1)]
    close = start_price
    prices = []
    # 模拟趋势：先涨后跌再涨
    for i in range(days):
        if i < days * 0.3:
            trend = 0.001  # 缓涨
        elif i < days * 0.5:
            trend = -0.002  # 下跌
        elif i < days * 0.7:
            trend = 0.002  # 上涨
        else:
            trend = -0.001  # 回调
        noise = np.random.randn() * volatility
        close *= (1 + trend + noise)
        prices.append(round(close, 2))
    
    df = pd.DataFrame({
        'trade_date': dates,
        'open': prices,
        'high': [p * (1 + abs(np.random.randn() * 0.01)) for p in prices],
        'low': [p * (1 - abs(np.random.randn() * 0.01)) for p in prices],
        'close': prices,
        'vol': [np.random.randint(50000, 500000) for _ in range(days)],
        'amount': [np.random.randint(1000000, 10000000) for _ in range(days)],
    })
    return df

def run_chanlun_test(ts_code, df):
    """运行缠论分析并打印中文分析报告"""
    df_analysis = df.copy()
    if 'vol' in df_analysis.columns and 'volume' not in df_analysis.columns:
        df_analysis['volume'] = df_analysis['vol']
    
    try:
        analyzer = ChanlunAnalyzer()
        result = analyzer.analyze(df_analysis)
    except Exception as e:
        print(f"  ❌ ChanlunAnalyzer 异常: {e}")
        return
    
    if not result.get('success') or 'error' in result:
        print(f"  ❌ 分析失败: {result.get('error', '未知错误')}")
        return
    
    # 提取分析信息
    summary = result.get('summary', {})
    strokes = result.get('strokes', [])
    segments = result.get('segments', [])
    zhongshu_list = result.get('zhongshu', [])
    divergence = result.get('divergence')
    buy_points = result.get('buy_points', [])
    sell_points = result.get('sell_points', [])
    trend = result.get('trend', 'unknown')
    
    latest_close = float(df['close'].iloc[-1])
    latest_date = df['trade_date'].iloc[-1]
    
    seg_count = summary.get('total_segments', 0)
    zs_count = summary.get('total_zhongshu', 0)
    
    # 走势结构
    print(f"========================================")
    print(f"{ts_code} — {latest_date} 缠论分析报告")
    print(f"========================================")
    print()
    print(f"【走势结构】")
    print(f"  趋势方向：{'上升' if trend == 'up' else '下降' if trend == 'down' else '待定'}（{seg_count}段, {zs_count}中枢）")
    print(f"  总笔数：{summary.get('total_strokes', 0)}")
    print(f"  总线段数：{seg_count}")
    if strokes:
        last = strokes[-1]
        print(f"  最后一笔：{'上升' if last.direction == 'up' else '下降'}笔 ({last.start_date}~{last.end_date}, [{last.start_price:.2f}->{last.end_price:.2f}])")
    print()
    
    # 中枢分析
    print(f"【中枢分析】")
    if zhongshu_list:
        zs = zhongshu_list[-1]
        print(f"  最新中枢区间：[{zs.low:.2f}, {zs.high:.2f}]，中心 {zs.center:.2f}")
        print(f"  中枢高度：{zs.high - zs.low:.2f}")
        if latest_close > zs.high:
            pct = (latest_close / zs.high - 1) * 100
            print(f"  价格位置：中枢上方（+{pct:.1f}%）")
        elif latest_close < zs.low:
            pct = (zs.low / latest_close - 1) * 100
            print(f"  价格位置：中枢下方（-{pct:.1f}%）")
        else:
            print(f"  价格位置：中枢内部")
        print(f"  中枢数量：{len(zhongshu_list)}")
    else:
        print("  尚未形成中枢结构")
    print()
    
    # 买卖点信号
    print(f"【买卖点信号】")
    BP_TYPE_CN = {
        'first_buy': '第一类买点', 'second_buy': '第二类买点', 'third_buy': '第三类买点',
        'first_sell': '第一类卖点', 'second_sell': '第二类卖点', 'third_sell': '第三类卖点',
    }
    if buy_points:
        print(f"  买入信号（{len(buy_points)}个）：")
        for p in buy_points:
            p_type = BP_TYPE_CN.get(p.type, p.type)
            p_price = p.position.get('price', 0)
            p_date = str(p.position.get('date', ''))[:10]
            p_pct = (latest_close / p_price - 1) * 100 if p_price else 0
            print(f"    {p_type} @{p_price:.2f} ({p_date}), 距当前+{p_pct:.0f}%, 置信度={p.confidence:.2f}")
    else:
        print("  无买入信号")
    if sell_points:
        print(f"  卖出信号（{len(sell_points)}个）：")
        for p in sell_points:
            p_type = BP_TYPE_CN.get(p.type, p.type)
            p_price = p.position.get('price', 0)
            p_date = str(p.position.get('date', ''))[:10]
            p_pct = (p_price / latest_close - 1) * 100 if p_price else 0
            print(f"    {p_type} @{p_price:.2f} ({p_date}), 距当前-{p_pct:.0f}%, 置信度={p.confidence:.2f}")
    else:
        print("  无卖出信号")
    if divergence:
        div_dir = {'up': '上涨', 'down': '下跌'}.get(divergence.direction, '')
        div_type_map = {'trend': '趋势', 'consolidation': '盘整', 'zhongshu': '中枢破坏'}
        div_type = div_type_map.get(divergence.type, divergence.type)
        print(f"  背驰：{div_dir}{div_type}背驰（置信度={divergence.confidence:.2f}）")
    print()
    
    # 操作建议（简单版）
    print(f"【操作建议】")
    has_buy = len(buy_points) > 0
    has_sell = len(sell_points) > 0
    
    if trend == 'up' and has_buy:
        best = max(buy_points, key=lambda p: p.confidence)
        bp = best.position.get('price', 0)
        bp_pct = (latest_close / bp - 1) * 100 if bp else 0
        if bp_pct < 20:
            print(f"  建议动作：买入建仓")
            print(f"  买入依据：上升趋势+{BP_TYPE_CN.get(best.type, best.type)}，距买点价+{bp_pct:.0f}%")
            print(f"  建仓策略：第一档 5%（试探）→ 确认后加至 10~15%")
            print(f"  止损设置：跌破买点价下方 5% 或出现第三类卖点")
        else:
            print(f"  建议动作：静待观察")
            print(f"  等待理由：最近买点已上涨{bp_pct:.0f}%，性价比较低")
            print(f"  等待信号：回调企稳或出现新的买点")
    elif trend == 'down' and has_sell:
        print(f"  建议动作：清仓规避")
        print(f"  清仓理由：下降趋势中出现卖点信号")
    elif trend == 'up':
        print(f"  建议动作：持仓观察")
        print(f"  当前状态：上升趋势延续，等待卖点信号")
    else:
        print(f"  建议动作：静待观察")
        print(f"  等待理由：趋势方向待定或无明确信号")
        print(f"  等待信号：趋势方向明朗后再介入")
    print()
    print(f"---")


if __name__ == '__main__':
    # 测试 1：默认模拟数据（先涨后跌再涨）
    print("=" * 60)
    print("测试1：默认趋势模拟数据")
    print("=" * 60)
    df1 = generate_test_data(500, start_price=20.0)
    run_chanlun_test("TEST.SZ", df1)
    
    # 测试 2：长期上涨数据
    print("=" * 60)
    print("测试2：长期上涨趋势")
    print("=" * 60)
    df2 = df1.copy()
    # 末尾添加持续上涨
    last_close = float(df2['close'].iloc[-1])
    new_prices = [last_close * (1 + 0.003) ** i for i in range(60)]
    extra_dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(60, 0, -1)]
    extra = pd.DataFrame({
        'trade_date': extra_dates[:len(new_prices)],
        'open': new_prices,
        'high': [p * 1.01 for p in new_prices],
        'low': [p * 0.99 for p in new_prices],
        'close': new_prices,
        'vol': [500000 for _ in range(len(new_prices))],
        'amount': [5000000 for _ in range(len(new_prices))],
    })
    df2 = pd.concat([df2.iloc[:-60], extra], ignore_index=True)
    run_chanlun_test("BULL.SZ", df2)
    
    # 测试 3：长期下跌数据
    print("=" * 60)
    print("测试3：长期下跌趋势")
    print("=" * 60)
    df3 = generate_test_data(500, start_price=50.0, volatility=0.025)
    last_close = float(df3['close'].iloc[-1])
    new_prices = [last_close * (1 - 0.002) ** i for i in range(60)]
    extra_dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(60, 0, -1)]
    extra = pd.DataFrame({
        'trade_date': extra_dates[:len(new_prices)],
        'open': new_prices,
        'high': [p * 1.01 for p in new_prices],
        'low': [p * 0.99 for p in new_prices],
        'close': new_prices,
        'vol': [500000 for _ in range(len(new_prices))],
        'amount': [5000000 for _ in range(len(new_prices))],
    })
    df3 = pd.concat([df3.iloc[:-60], extra], ignore_index=True)
    run_chanlun_test("BEAR.SZ", df3)
