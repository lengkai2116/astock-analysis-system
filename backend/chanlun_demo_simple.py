#!/usr/bin/env python
"""
缠论K线图形演示脚本 - 简化版
展示：分型、笔的构建过程
"""
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # 无GUI环境
import matplotlib.pyplot as plt
from app import create_app
from app.models import DailyData, db

# ============================================================================
# 第一部分：数据获取
# ============================================================================

def get_stock_data(ts_code, limit=100):
    """获取股票日线数据"""
    app = create_app()
    with app.app_context():
        data = DailyData.query.filter_by(ts_code=ts_code)\
            .order_by(DailyData.trade_date.asc())\
            .limit(limit)\
            .all()
        
        df = pd.DataFrame([{
            'date': d.trade_date,
            'open': float(d.open),
            'high': float(d.high),
            'low': float(d.low),
            'close': float(d.close)
        } for d in data])
        df['date'] = pd.to_datetime(df['date'])
        return df


# ============================================================================
# 第二部分：缠论核心算法
# ============================================================================

class KLine:
    """K线数据结构"""
    def __init__(self, idx, open, high, low, close, date):
        self.idx = idx
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.date = date
    
    def __repr__(self):
        return f"K[{self.idx}]:{self.high:.2f}/{self.low:.2f} @{self.date.strftime('%Y-%m-%d')}"


def is_contained(k1, k2):
    """检查K2是否被K1包含（或者反过来）"""
    return (k2.high <= k1.high and k2.low >= k1.low) or \
           (k1.high <= k2.high and k1.low >= k2.low)


def merge_contain(klines_raw):
    """包含关系处理：处理原始K线序列成无包含序列"""
    if len(klines_raw) < 2:
        return klines_raw
    
    result = []
    direction = None  # 'up' or 'down'
    
    for i in range(len(klines_raw)):
        if i == 0:
            result.append(klines_raw[0])
            continue
        
        current = klines_raw[i]
        prev = result[-1]
        
        # 确定方向
        if direction is None:
            if current.high > prev.high:
                direction = 'up'
            else:
                direction = 'down'
        
        # 检查包含关系
        if is_contained(prev, current):
            # 合并
            if direction == 'up':
                new_high = max(prev.high, current.high)
                new_low = max(prev.low, current.low)
            else:
                new_high = min(prev.high, current.high)
                new_low = min(prev.low, current.low)
            
            merged = KLine(
                idx=prev.idx,
                open=prev.open,
                high=new_high,
                low=new_low,
                close=current.close,
                date=current.date
            )
            result[-1] = merged
        else:
            result.append(current)
            # 更新方向
            if current.high > prev.high:
                direction = 'up'
            else:
                direction = 'down'
    
    return result


def find_fractals(klines):
    """识别顶底分型"""
    fractals = []
    
    for i in range(1, len(klines) - 1):
        prev = klines[i-1]
        curr = klines[i]
        next_k = klines[i+1]
        
        # 顶分型：中间高
        if (curr.high > prev.high and curr.high > next_k.high and
            curr.low > prev.low and curr.low > next_k.low):
            fractals.append({
                'type': 'top',
                'idx': i,
                'kline': curr,
                'price': curr.high,
                'date': curr.date
            })
        
        # 底分型：中间低
        if (curr.low < prev.low and curr.low < next_k.low and
            curr.high < prev.high and curr.high < next_k.high):
            fractals.append({
                'type': 'bottom',
                'idx': i,
                'kline': curr,
                'price': curr.low,
                'date': curr.date
            })
    
    return fractals


def build_strokes(fractals, klines):
    """构建笔（简化版）"""
    strokes = []
    
    i = 0
    while i < len(fractals) - 1:
        f1 = fractals[i]
        f2 = fractals[i+1]
        
        # 确保分型交替（顶-底或底-顶）
        if f1['type'] == f2['type']:
            i += 1
            continue
        
        # 检查间距（至少1根独立K线）
        k_count = f2['idx'] - f1['idx']
        if k_count < 2:  # idx差至少2（中间至少1根K线）
            i += 1
            continue
        
        # 检查方向
        valid = False
        if f1['type'] == 'bottom' and f2['type'] == 'top':
            # 向上笔：顶 > 底
            if f2['price'] > f1['price']:
                valid = True
                direction = 'up'
        elif f1['type'] == 'top' and f2['type'] == 'bottom':
            # 向下笔：顶 > 底
            if f1['price'] > f2['price']:
                valid = True
                direction = 'down'
        
        if valid:
            strokes.append({
                'start_idx': f1['idx'],
                'end_idx': f2['idx'],
                'start_price': f1['price'],
                'end_price': f2['price'],
                'start_date': f1['date'],
                'end_date': f2['date'],
                'direction': direction
            })
            i += 2
        else:
            i += 1
    
    return strokes


# ============================================================================
# 第三部分：图形绘制（简化版）
# ============================================================================

def plot_simple_chanlun(df, klines_no_contain, fractals, strokes, 
                        output_file='chanlun_demo.png'):
    """绘制简单的缠论K线图"""
    fig, ax = plt.subplots(figsize=(15, 9), dpi=120)
    ax.set_facecolor('#f5f5f5')
    
    # 绘制K线
    for i in range(len(df)):
        row = df.iloc[i]
        open_p = row['open']
        close_p = row['close']
        high_p = row['high']
        low_p = row['low']
        
        # 绘制上下影线
        ax.vlines(i, low_p, high_p, color='#333333', linewidth=1)
        
        # 绘制实体
        if close_p >= open_p:
            # 阳线
            ax.vlines(i, open_p, close_p, color='#ff4757', linewidth=4)
        else:
            # 阴线
            ax.vlines(i, close_p, open_p, color='#2ed573', linewidth=4)
    
    # 绘制分型
    for f in fractals:
        idx = f['idx']
        price = f['price']
        if f['type'] == 'top':
            ax.scatter(idx, price, marker='v', color='#ff4757', s=80, zorder=5,
                       label='Top' if f == fractals[0] else "")
        else:
            ax.scatter(idx, price, marker='^', color='#2ed573', s=80, zorder=5,
                       label='Bottom' if f == fractals[0] else "")
    
    # 绘制笔
    for stroke in strokes:
        x = [stroke['start_idx'], stroke['end_idx']]
        y = [stroke['start_price'], stroke['end_price']]
        color = '#ff4757' if stroke['direction'] == 'up' else '#2ed573'
        ax.plot(x, y, color=color, linewidth=3, linestyle='-', zorder=3,
                label='Up Stroke' if stroke == strokes[0] and stroke['direction'] == 'up' 
                else 'Down Stroke' if stroke == strokes[0] else "")
    
    # 美化图表
    ax.set_title('Chanlun Analysis - Pingan Bank', fontsize=15, pad=20, fontweight='bold')
    ax.set_xlabel('K-Line Index', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.legend(loc='best', fontsize=10)
    
    # 日期标注
    date_indices = range(0, len(df), max(1, len(df)//10))
    ax.set_xticks(date_indices)
    ax.set_xticklabels([df.iloc[i]['date'].strftime('%Y-%m-%d') for i in date_indices], rotation=45)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"✅ Chart saved to: {output_file}")
    return output_file


def print_summary(df, klines_no_contain, fractals, strokes):
    """打印信息汇总"""
    print("="*80)
    print("📊 缠论分析统计")
    print("="*80)
    print(f"原始K线数: {len(df)}")
    print(f"无包含K线数: {len(klines_no_contain)}")
    print(f"顶分型: {len([f for f in fractals if f['type']=='top'])}")
    print(f"底分型: {len([f for f in fractals if f['type']=='bottom'])}")
    print(f"笔数: {len(strokes)}")
    print(f"向上笔: {len([s for s in strokes if s['direction']=='up'])}")
    print(f"向下笔: {len([s for s in strokes if s['direction']=='down'])}")
    print("="*80)
    
    if strokes:
        print("\n📝 笔详细信息:")
        for i, s in enumerate(strokes, 1):
            start_date = s['start_date'].strftime('%Y-%m-%d')
            end_date = s['end_date'].strftime('%Y-%m-%d')
            dir_str = "↗️ 向上" if s['direction'] == 'up' else "↘️ 向下"
            print(f"  笔{i}: {start_date} -> {end_date} [{dir_str}]")


# ============================================================================
# 主程序
# ============================================================================

def main():
    print("🚀 缠论K线图形演示（简化版）")
    print("="*80)
    
    # 1. 获取数据
    print("📥 正在获取数据...")
    df = get_stock_data('000001.SZ', limit=80)
    
    if len(df) < 30:
        print("❌ 数据不足！")
        return
    
    print(f"✅ 获取到 {len(df)} 条日线数据 (范围: {df.iloc[0]['date']} ~ {df.iloc[-1]['date']})")
    
    # 2. 构建K线对象
    print("🔄 正在处理K线...")
    klines_raw = []
    for idx, row in df.iterrows():
        klines_raw.append(KLine(
            idx=idx,
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            date=row['date']
        ))
    
    # 3. 包含处理
    klines_no_contain = merge_contain(klines_raw)
    print(f"✅ 包含处理完成: {len(klines_no_contain)} 根K线")
    
    # 4. 找分型
    fractals = find_fractals(klines_no_contain)
    print(f"✅ 分型识别: {len(fractals)} 个")
    
    # 5. 构建笔
    strokes = build_strokes(fractals, klines_no_contain)
    print(f"✅ 笔构建: {len(strokes)} 笔")
    
    # 6. 画图
    print("\n🎨 正在生成图表...")
    output_file = '/app/chanlun_demo.png'
    plot_simple_chanlun(df, klines_no_contain, fractals, strokes, output_file)
    
    # 7. 打印总结
    print_summary(df, klines_no_contain, fractals, strokes)
    
    print("\n🎉 演示完成！")


if __name__ == '__main__':
    main()
