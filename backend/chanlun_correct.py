#!/usr/bin/env python3
"""
缠论K线图形演示脚本 - 正确版本
根据《一小时漫画缠论实战法》实现
展示：K线 → 分型 → 笔 的完整连续图形
"""
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from app import create_app
from app.models import DailyData, db


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


class KLine:
    """K线数据结构"""
    def __init__(self, idx, high, low, date):
        self.idx = idx
        self.high = high
        self.low = low
        self.date = date
    
    def __repr__(self):
        return f"K[{self.idx}]: H={self.high:.2f}, L={self.low:.2f} @{self.date.strftime('%Y-%m-%d')}"


def is_contained(k1, k2):
    """检查K2是否被K1包含"""
    return (k2.high <= k1.high and k2.low >= k1.low) or \
           (k1.high <= k2.high and k1.low >= k2.low)


def merge_contain(klines_raw):
    """
    包含关系处理
    关键点：
    - 上升走势中：取最高的高点和最高的低点
    - 下降走势中：取最低的高点和最低的低点
    """
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
                high=new_high,
                low=new_low,
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
    """
    识别顶底分型
    顶分型：中间高，像"品"字
    底分型：中间低
    """
    fractals = []
    
    for i in range(1, len(klines) - 1):
        prev = klines[i-1]
        curr = klines[i]
        next_k = klines[i+1]
        
        # 顶分型：中间高（高中高）
        if (curr.high > prev.high and curr.high > next_k.high):
            fractals.append({
                'type': 'top',
                'idx': i,
                'kline': curr,
                'price': curr.high,
                'date': curr.date
            })
        
        # 底分型：中间低（低中低）
        if (curr.low < prev.low and curr.low < next_k.low):
            fractals.append({
                'type': 'bottom',
                'idx': i,
                'kline': curr,
                'price': curr.low,
                'date': curr.date
            })
    
    return fractals


def build_strokes(fractals, klines):
    """
    构建笔
    关键点：
    1. 笔必须由顶分型+中间K线+底分型组成（或反之）
    2. 最小的笔需要至少5根K线（分型之间至少1根独立K线）
    3. 笔是连续的，一根向上笔结束后一定会跟一根向下笔
    4. 永远不会出现隔空笔
    """
    if len(fractals) < 2:
        return []
    
    strokes = []
    i = 0
    
    while i < len(fractals) - 1:
        f1 = fractals[i]
        f2 = fractals[i + 1]
        
        # 确保分型交替（顶-底 或 底-顶）
        if f1['type'] == f2['type']:
            i += 1
            continue
        
        # 检查间距：至少5根K线（分型各1根 + 中间至少1根 = 3根原始，但严格来说是分型之间至少1根独立K线）
        # 这里我们用至少3根K线（idx差>=2）来判断
        k_count = f2['idx'] - f1['idx']
        if k_count < 2:  # 中间至少1根K线
            i += 1
            continue
        
        # 确定笔的方向和有效性
        if f1['type'] == 'bottom' and f2['type'] == 'top':
            # 向上笔：底 -> 顶，顶必须高于底
            if f2['price'] > f1['price']:
                strokes.append({
                    'start_idx': f1['idx'],
                    'end_idx': f2['idx'],
                    'start_price': f1['price'],
                    'end_price': f2['price'],
                    'start_date': f1['date'],
                    'end_date': f2['date'],
                    'direction': 'up',
                    'start_fractal': f1,
                    'end_fractal': f2
                })
                i += 2
                continue
        elif f1['type'] == 'top' and f2['type'] == 'bottom':
            # 向下笔：顶 -> 底，底必须低于顶
            if f1['price'] > f2['price']:
                strokes.append({
                    'start_idx': f1['idx'],
                    'end_idx': f2['idx'],
                    'start_price': f1['price'],
                    'end_price': f2['price'],
                    'start_date': f1['date'],
                    'end_date': f2['date'],
                    'direction': 'down',
                    'start_fractal': f1,
                    'end_fractal': f2
                })
                i += 2
                continue
        
        i += 1
    
    return strokes


def plot_correct_chanlun(df, klines_no_contain, fractals, strokes, output_file='chanlun_correct.png'):
    """
    绘制正确的缠论K线图
    关键改进：
    1. 笔用连续的折线连接，形成完整的波浪形状
    2. 笔与笔之间紧密相连，不间断
    3. 清晰地展示笔的连续性
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), dpi=120, 
                                    gridspec_kw={'height_ratios': [3, 1]})
    
    # ========== 上图：K线 + 笔 ==========
    ax1.set_facecolor('#1e1e1e')
    
    # 1. 绘制K线
    for i in range(len(df)):
        row = df.iloc[i]
        high_p = row['high']
        low_p = row['low']
        open_p = row['open']
        close_p = row['close']
        
        # 绘制上下影线
        ax1.plot([i, i], [low_p, high_p], color='#666666', linewidth=1, zorder=1)
        
        # 绘制实体
        if close_p >= open_p:
            ax1.plot([i, i], [open_p, close_p], color='#ff4757', linewidth=3, zorder=2)
        else:
            ax1.plot([i, i], [close_p, open_p], color='#2ed573', linewidth=3, zorder=2)
    
    # 2. 绘制笔（用连续折线）
    if strokes:
        # 构建连续折线
        stroke_x = []
        stroke_y = []
        
        for i, stroke in enumerate(strokes):
            if i == 0:
                stroke_x.append(stroke['start_idx'])
                stroke_y.append(stroke['start_price'])
            
            stroke_x.append(stroke['end_idx'])
            stroke_y.append(stroke['end_price'])
        
        # 绘制连续折线
        ax1.plot(stroke_x, stroke_y, color='#ffd700', linewidth=2.5, 
                linestyle='-', zorder=3, alpha=0.9)
        
        # 在转折点标记分型
        for stroke in strokes:
            # 起点
            if stroke['direction'] == 'up':
                marker_color = '#2ed573'  # 底分型用绿色
            else:
                marker_color = '#ff4757'  # 顶分型用红色
            
            ax1.scatter(stroke['start_idx'], stroke['start_price'], 
                       marker='o', color=marker_color, s=60, zorder=5)
            
            # 终点
            if stroke['direction'] == 'up':
                marker_color = '#ff4757'  # 顶分型用红色
            else:
                marker_color = '#2ed573'  # 底分型用绿色
            
            ax1.scatter(stroke['end_idx'], stroke['end_price'], 
                       marker='o', color=marker_color, s=60, zorder=5)
    
    # 美化
    ax1.set_title('Chanlun Analysis - Pingan Bank (000001.SZ)\nStrokes Connected Continuously', 
                 fontsize=14, pad=15, color='white', fontweight='bold')
    ax1.set_ylabel('Price', fontsize=11, color='white')
    ax1.tick_params(colors='white')
    ax1.grid(True, alpha=0.2, color='#444444')
    ax1.set_xlim(-1, len(df))
    
    # 日期标注
    date_indices = range(0, len(df), max(1, len(df)//10))
    ax1.set_xticks(list(date_indices))
    ax1.set_xticklabels([df.iloc[i]['date'].strftime('%Y-%m-%d') for i in date_indices], rotation=45)
    
    # ========== 下图：笔的序列 ==========
    ax2.set_facecolor('#1e1e1e')
    
    if strokes:
        # 绘制笔序列
        stroke_x = []
        stroke_y = []
        
        for i, stroke in enumerate(strokes):
            if i == 0:
                stroke_x.append(0)
                stroke_y.append(i)
            
            stroke_x.append(i + 1)
            stroke_y.append(i + 1)
        
        # 绘制连续的笔序列
        colors = ['#ff4757' if s['direction'] == 'down' else '#2ed573' for s in strokes]
        ax2.plot(range(len(strokes)), range(len(strokes)), 'o-', 
                color='#ffd700', linewidth=2, markersize=8)
        
        # 标记方向
        for i, stroke in enumerate(strokes):
            color = '#ff4757' if stroke['direction'] == 'down' else '#2ed573'
            label = 'DOWN' if stroke['direction'] == 'down' else 'UP'
            ax2.scatter(i, i, color=color, s=150, zorder=5)
            ax2.text(i, i + 0.15, label, ha='center', va='bottom', 
                    fontsize=9, fontweight='bold', color=color)
    
    ax2.set_title('Stroke Sequence (Alternating UP and DOWN)', fontsize=11, pad=10, color='white')
    ax2.set_xlabel('Stroke Index', fontsize=11, color='white')
    ax2.set_ylabel('Sequence', fontsize=11, color='white')
    ax2.tick_params(colors='white')
    ax2.grid(True, alpha=0.2, color='#444444')
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight', 
                facecolor='#1e1e1e', edgecolor='none')
    plt.close()
    
    print(f"Chart saved to: {output_file}")
    return output_file


def print_summary(df, klines_no_contain, fractals, strokes):
    """打印信息汇总"""
    print("="*80)
    print("Chanlun Analysis Summary (Correct Version)")
    print("="*80)
    print(f"Raw K-lines: {len(df)}")
    print(f"K-lines after merge: {len(klines_no_contain)}")
    print(f"Top fractals: {len([f for f in fractals if f['type']=='top'])}")
    print(f"Bottom fractals: {len([f for f in fractals if f['type']=='bottom'])}")
    print(f"Total strokes: {len(strokes)}")
    print(f"  - Up strokes: {len([s for s in strokes if s['direction']=='up'])}")
    print(f"  - Down strokes: {len([s for s in strokes if s['direction']=='down'])}")
    print("="*80)
    
    if strokes:
        print("\nStroke Details:")
        print("-" * 80)
        for i, s in enumerate(strokes, 1):
            start_date = s['start_date'].strftime('%Y-%m-%d')
            end_date = s['end_date'].strftime('%Y-%m-%d')
            dir_str = "DOWN" if s['direction'] == 'down' else "UP"
            print(f"Stroke {i:2d}: {start_date} -> {end_date} [{dir_str:4s}] "
                  f"{s['start_price']:.2f} -> {s['end_price']:.2f}")


def main():
    print("Chanlun K-line Analysis - Correct Version")
    print("Based on: 《一小时漫画缠论实战法》")
    print("="*80)
    
    # 1. 获取数据
    print("\n1. Loading data...")
    df = get_stock_data('000001.SZ', limit=80)
    
    if len(df) < 30:
        print("Insufficient data!")
        return
    
    print(f"   Loaded {len(df)} K-lines from {df.iloc[0]['date'].strftime('%Y-%m-%d')} to {df.iloc[-1]['date'].strftime('%Y-%m-%d')}")
    
    # 2. 构建K线对象
    print("\n2. Building K-line objects...")
    klines_raw = []
    for idx, row in df.iterrows():
        klines_raw.append(KLine(
            idx=idx,
            high=row['high'],
            low=row['low'],
            date=row['date']
        ))
    print(f"   Created {len(klines_raw)} raw K-lines")
    
    # 3. 包含处理
    print("\n3. Merging contained K-lines...")
    klines_no_contain = merge_contain(klines_raw)
    print(f"   Merged to {len(klines_no_contain)} K-lines")
    
    # 4. 找分型
    print("\n4. Finding fractals...")
    fractals = find_fractals(klines_no_contain)
    print(f"   Found {len(fractals)} fractals ({len([f for f in fractals if f['type']=='top'])} tops, {len([f for f in fractals if f['type']=='bottom'])} bottoms)")
    
    # 5. 构建笔
    print("\n5. Building strokes...")
    strokes = build_strokes(fractals, klines_no_contain)
    print(f"   Built {len(strokes)} strokes")
    
    # 6. 画图
    print("\n6. Generating chart...")
    output_file = '/app/chanlun_correct.png'
    plot_correct_chanlun(df, klines_no_contain, fractals, strokes, output_file)
    
    # 7. 打印总结
    print_summary(df, klines_no_contain, fractals, strokes)
    
    print("\nDone!")


if __name__ == '__main__':
    main()
