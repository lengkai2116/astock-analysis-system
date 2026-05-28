#!/usr/bin/env python3
"""
缠论K线图形演示脚本 - 严格按《一小时漫画缠论实战法》规范实现
修复：分型位置与K线对应问题
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from datetime import datetime, timedelta

plt.rcParams['font.sans-serif'] = ['SimHei', 'Heiti TC', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

class KLine:
    def __init__(self, idx, high, low, date=None):
        self.idx = idx  # 原始K线索引
        self.high = high
        self.low = low
        self.date = date


def generate_simulation_data(base_price=100, days=150, volatility=0.02):
    np.random.seed(42)
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(days)]
    klines = []
    price = base_price
    trend_up = True
    
    for i in range(days):
        if i % 15 == 0 and i > 0:
            trend_up = not trend_up
        
        if trend_up:
            change = np.random.uniform(0, volatility * price * 2)
        else:
            change = np.random.uniform(-volatility * price * 2, 0)
        
        high = price + abs(np.random.normal(0, volatility * price * 1.5))
        low = price - abs(np.random.normal(0, volatility * price * 1.5))
        
        high = max(high, price + 2)
        low = min(low, price - 2)
        
        klines.append(KLine(i, high, low, dates[i]))
        price = (high + low) / 2 + change
    
    return klines


def has_contain_relation(k1, k2):
    return (k2.high <= k1.high and k2.low >= k1.low) or \
           (k1.high <= k2.high and k1.low >= k2.low)


def merge_contain(klines_raw):
    if len(klines_raw) < 2:
        return klines_raw
    
    result = [klines_raw[0]]
    direction = 'up' if klines_raw[1].high > klines_raw[0].high else 'down'
    
    for i in range(1, len(klines_raw)):
        current = klines_raw[i]
        prev = result[-1]
        
        if has_contain_relation(prev, current):
            if direction == 'up':
                new_high = max(prev.high, current.high)
                new_low = max(prev.low, current.low)
            else:
                new_high = min(prev.high, current.high)
                new_low = min(prev.low, current.low)
            
            # 保留原始idx（起始K线），但更新高低点
            merged = KLine(prev.idx, new_high, new_low, current.date)
            result[-1] = merged
        else:
            result.append(current)
            direction = 'up' if current.high > prev.high else 'down'
    
    return result


def identify_fractals(klines):
    """识别顶底分型 - 构建严格交替的分型序列"""
    raw_fractals = []
    
    for i in range(1, len(klines) - 1):
        prev = klines[i-1]
        curr = klines[i]
        next_k = klines[i+1]
        
        if curr.high > prev.high and curr.high > next_k.high:
            raw_fractals.append({
                'type': 'top', 
                'idx': curr.idx,  # 关键：保留原始K线idx，不是处理后的idx
                'high': curr.high, 
                'low': curr.low
            })
        
        if curr.low < prev.low and curr.low < next_k.low:
            raw_fractals.append({
                'type': 'bottom', 
                'idx': curr.idx,  # 关键：保留原始K线idx
                'high': curr.high, 
                'low': curr.low
            })
    
    raw_fractals.sort(key=lambda x: x['idx'])
    
    filtered = []
    
    for f in raw_fractals:
        if not filtered:
            filtered.append(f)
            continue
        
        last = filtered[-1]
        
        if last['type'] != f['type']:
            filtered.append(f)
        else:
            if f['type'] == 'top':
                if f['high'] > last['high']:
                    filtered[-1] = f
            else:
                if f['low'] < last['low']:
                    filtered[-1] = f
    
    final = []
    for f in filtered:
        if not final:
            final.append(f)
        elif final[-1]['type'] != f['type']:
            final.append(f)
    
    return final


def build_strokes(fractals, klines, min_klines=5):
    if len(fractals) < 2:
        return []
    
    strokes = []
    i = 0
    
    while i < len(fractals) - 1:
        f1 = fractals[i]
        f2 = fractals[i + 1]
        
        if f1['type'] == f2['type']:
            i += 1
            continue
        
        # 使用原始idx计算k线跨度，而不是处理后的
        kline_count = f2['idx'] - f1['idx'] + 1
        
        if kline_count < min_klines:
            i += 1
            continue
        
        if f1['type'] == 'bottom' and f2['type'] == 'top':
            strokes.append({
                'start_idx': f1['idx'],
                'end_idx': f2['idx'],
                'start_price': f1['low'],
                'end_price': f2['high'],
                'direction': 'up'
            })
            i += 2
        elif f1['type'] == 'top' and f2['type'] == 'bottom':
            strokes.append({
                'start_idx': f1['idx'],
                'end_idx': f2['idx'],
                'start_price': f1['high'],
                'end_price': f2['low'],
                'direction': 'down'
            })
            i += 2
        else:
            i += 1
    
    return strokes


def build_segments(strokes):
    if len(strokes) < 3:
        return []
    
    segments = []
    
    def has_overlap(s1, s2):
        return s1['start_price'] <= s2['end_price'] and s1['end_price'] >= s2['start_price']
    
    i = 0
    while i <= len(strokes) - 3:
        s1, s2, s3 = strokes[i], strokes[i+1], strokes[i+2]
        
        if has_overlap(s1, s2) and has_overlap(s2, s3):
            segments.append({
                'start_idx': s1['start_idx'],
                'end_idx': s3['end_idx'],
                'direction': s1['direction'],
                'strokes': [s1, s2, s3]
            })
            i += 3
        else:
            i += 1
    
    return segments


def find_central_pivot(strokes):
    if len(strokes) < 5:
        return None
    
    for i in range(len(strokes) - 4):
        candidates = strokes[i:i+5]
        highs = [s['start_price'] if s['direction'] == 'down' else s['end_price'] for s in candidates]
        lows = [s['end_price'] if s['direction'] == 'down' else s['start_price'] for s in candidates]
        
        ZG = min(highs)
        ZD = max(lows)
        
        if ZG > ZD:
            return {
                'start_idx': candidates[0]['start_idx'],
                'end_idx': candidates[-1]['end_idx'],
                'ZG': ZG, 'ZD': ZD,
                'components': candidates
            }
    
    return None


def plot_chanlun(klines_raw, klines_merged, fractals, strokes, segments, pivot, output_file):
    fig = plt.figure(figsize=(24, 18), dpi=120)
    gs = fig.add_gridspec(3, 1, height_ratios=[4, 1, 1], hspace=0.2)
    
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor('#1a1a2e')
    
    for k in klines_raw:
        ax1.plot([k.idx, k.idx], [k.low, k.high], color='#3a3a4e', linewidth=1, alpha=0.35, zorder=1)
    
    for k in klines_merged:
        ax1.plot([k.idx, k.idx], [k.low, k.high], color='#8a8aae', linewidth=2, zorder=2)
    
    for f in fractals:
        if f['type'] == 'top':
            ax1.scatter(f['idx'], f['high'], marker='v', color='#ff6b6b', s=250, zorder=6, edgecolors='white', linewidth=2)
            ax1.annotate('TOP', (f['idx'], f['high']), textcoords="offset points", xytext=(0, 15), fontsize=11, color='#ff6b6b', ha='center', fontweight='bold')
        else:
            ax1.scatter(f['idx'], f['low'], marker='^', color='#4ecdc4', s=250, zorder=6, edgecolors='white', linewidth=2)
            ax1.annotate('BOTTOM', (f['idx'], f['low']), textcoords="offset points", xytext=(0, -18), fontsize=11, color='#4ecdc4', ha='center', fontweight='bold')
    
    if strokes:
        stroke_x = []
        stroke_y = []
        
        for stroke in strokes:
            stroke_x.append(stroke['start_idx'])
            stroke_y.append(stroke['start_price'])
            stroke_x.append(stroke['end_idx'])
            stroke_y.append(stroke['end_price'])
        
        ax1.plot(stroke_x, stroke_y, color='#ffd93d', linewidth=4.5, linestyle='-', zorder=5, alpha=0.95)
        
        for i, stroke in enumerate(strokes, 1):
            mid_x = (stroke['start_idx'] + stroke['end_idx']) / 2
            mid_y = (stroke['start_price'] + stroke['end_price']) / 2
            direction = 'UP' if stroke['direction'] == 'up' else 'DOWN'
            color = '#4ecdc4' if stroke['direction'] == 'up' else '#ff6b6b'
            
            ax1.annotate(f'STROKE {i} ({direction})', (mid_x, mid_y), textcoords="offset points", xytext=(0, 0), fontsize=11, fontweight='bold', color=color, ha='center', va='center',
                        bbox=dict(boxstyle='round,pad=0.4', facecolor='black', alpha=0.9, edgecolor=color, linewidth=2))
    
    if segments:
        for seg in segments:
            seg_color = '#74b9ff'
            ax1.plot([seg['start_idx'], seg['end_idx']], [seg['strokes'][0]['start_price'], seg['strokes'][0]['start_price']], color=seg_color, linewidth=15, alpha=0.2, zorder=3)
            ax1.text((seg['start_idx'] + seg['end_idx'])/2, seg['strokes'][0]['start_price']*1.04, f'SEGMENT-{seg["direction"].upper()}', fontsize=13, color=seg_color, fontweight='bold', ha='center')
    
    if pivot:
        rect = patches.Rectangle((pivot['start_idx'], pivot['ZD']), pivot['end_idx'] - pivot['start_idx'] + 3, pivot['ZG'] - pivot['ZD'], linewidth=5, edgecolor='#ffa502', facecolor='#ffa502', alpha=0.25, zorder=4)
        ax1.add_patch(rect)
        ax1.text(pivot['start_idx'] - 1, pivot['ZG'] * 1.01, f'ZG = {pivot["ZG"]:.2f}', fontsize=13, color='#ffa502', fontweight='bold')
        ax1.text(pivot['start_idx'] - 1, pivot['ZD'] * 0.99, f'ZD = {pivot["ZD"]:.2f}', fontsize=13, color='#ffa502', fontweight='bold')
        ax1.text((pivot['start_idx'] + pivot['end_idx'])/2 + 1.5, (pivot['ZG'] + pivot['ZD'])/2, 'CENTRAL PIVOT', fontsize=15, color='#ffa502', fontweight='bold', ha='center',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='black', alpha=0.85, edgecolor='#ffa502', linewidth=2))
    
    all_prices = [k.high for k in klines_raw] + [k.low for k in klines_raw]
    y_min, y_max = min(all_prices) * 0.88, max(all_prices) * 1.12
    
    ax1.set_title('CHANLUN COMPLETE STRUCTURE\nK-line -> Contain -> Fractal -> Stroke -> Segment -> Central Pivot', fontsize=18, pad=25, color='white', fontweight='bold')
    ax1.set_ylabel('Price', fontsize=14, color='white')
    ax1.tick_params(colors='white', labelsize=11)
    ax1.grid(True, alpha=0.15, color='#444466')
    ax1.set_xlim(-3, len(klines_raw) + 3)
    ax1.set_ylim(y_min, y_max)
    
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color='#8a8aae', lw=2, label='Chan K-line'),
        Line2D([0], [0], marker='v', color='#ff6b6b', linestyle='None', markersize=12, label='Top Fractal'),
        Line2D([0], [0], marker='^', color='#4ecdc4', linestyle='None', markersize=12, label='Bottom Fractal'),
        Line2D([0], [0], color='#ffd93d', lw=4, label='Stroke'),
        Line2D([0], [0], color='#74b9ff', lw=8, alpha=0.3, label='Segment'),
        Line2D([0], [0], color='#ffa502', lw=4, label='Central Pivot')
    ]
    ax1.legend(handles=legend_elements, loc='upper left', facecolor='#2a2a3e', edgecolor='#666688', labelcolor='white', fontsize=10, framealpha=0.95)
    
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.set_facecolor('#1a1a2e')
    for k in klines_raw:
        ax2.plot([k.idx, k.idx], [k.low, k.high], color='#4a4a6e', linewidth=1.5, alpha=0.45)
    for k in klines_merged:
        ax2.plot([k.idx, k.idx], [k.low, k.high], color='#aaaaee', linewidth=2.5)
    ax2.set_title(f'STEP 1: Contain Relation Processing  ({len(klines_raw)} K-lines -> {len(klines_merged)} K-lines after merge)', fontsize=13, pad=12, color='white', fontweight='bold')
    ax2.tick_params(colors='white')
    ax2.grid(True, alpha=0.1, color='#444466')
    ax2.set_xlim(-3, len(klines_raw) + 3)
    ax2.set_ylim(y_min, y_max)
    
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_facecolor('#1a1a2e')
    for f in fractals:
        y = 0.72 if f['type'] == 'top' else 0.28
        color = '#ff6b6b' if f['type'] == 'top' else '#4ecdc4'
        marker = 'v' if f['type'] == 'top' else '^'
        ax3.scatter(f['idx'], y, marker=marker, color=color, s=150, edgecolors='white', linewidth=1.5)
        ax3.text(f['idx'], y + (0.1 if f['type'] == 'top' else -0.12), f['type'][0].upper(), fontsize=10, color=color, ha='center', fontweight='bold')
    
    top_count = len([f for f in fractals if f['type'] == 'top'])
    bottom_count = len([f for f in fractals if f['type'] == 'bottom'])
    ax3.set_title(f'STEP 2: Fractal Identification  (Top: {top_count}, Bottom: {bottom_count}) - Strictly Alternating', fontsize=13, pad=12, color='white', fontweight='bold')
    ax3.set_yticks([0.28, 0.72])
    ax3.set_yticklabels(['BOTTOM', 'TOP'], color='white', fontsize=12, fontweight='bold')
    ax3.tick_params(axis='x', colors='white', labelsize=10)
    ax3.grid(True, alpha=0.1, color='#444466')
    ax3.set_xlim(-3, len(klines_raw) + 3)
    
    plt.savefig(output_file, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    print(f"Chart saved: {output_file}")


def main():
    print("="*70)
    print("CHANLUN DIAGRAM GENERATOR v4 - Fixed Fractal Position Mapping")
    print("Based on: 《一小时漫画缠论实战法》")
    print("="*70)
    
    print("\n[Step 1] Generating data...")
    klines_raw = generate_simulation_data(base_price=100, days=150, volatility=0.02)
    print(f"    -> Generated {len(klines_raw)} K-lines")
    
    print("\n[Step 2] Processing contain relations...")
    klines_merged = merge_contain(klines_raw)
    print(f"    -> Merged: {len(klines_raw)} -> {len(klines_merged)} K-lines")
    
    print("\n[Step 3] Identifying fractals (strictly alternating)...")
    fractals = identify_fractals(klines_merged)
    print(f"    -> Found {len(fractals)} fractals")
    
    print("    -> Fractal sequence:")
    seq = " -> ".join([f"{f['type'][0].upper()}({f['idx']})" for f in fractals])
    print(f"       {seq}")
    
    print("\n[Step 4] Building strokes (min 5 K-lines per stroke)...")
    strokes = build_strokes(fractals, klines_merged, min_klines=5)
    print(f"    -> Built {len(strokes)} strokes")
    
    print("\n[Step 5] Building segments (min 3 strokes with overlap)...")
    segments = build_segments(strokes)
    print(f"    -> Built {len(segments)} segments")
    
    print("\n[Step 6] Finding central pivot (5 strokes structure)...")
    pivot = find_central_pivot(strokes)
    print(f"    -> Found: {'Yes' if pivot else 'No'}")
    
    print("\n[Step 7] Generating chart...")
    output_file = '/Users/kalence/Desktop/测试/chanlun_complete_diagram.png'
    plot_chanlun(klines_raw, klines_merged, fractals, strokes, segments, pivot, output_file)
    
    print("\n" + "="*70)
    print("ANALYSIS RESULT:")
    print("="*70)
    print(f"K-lines: {len(klines_raw)} -> {len(klines_merged)}")
    print(f"Fractals: {len(fractals)}")
    
    print(f"\nStrokes (Min 5 K-lines per stroke):")
    for i, s in enumerate(strokes, 1):
        direction = "UP" if s['direction'] == 'up' else "DOWN"
        k_count = s['end_idx'] - s['start_idx'] + 1
        print(f"  #{i}: {direction:5s} | {k_count} K-lines")
    
    print(f"\nSegments: {len(segments)}")
    print(f"Central Pivot: {'Found' if pivot else 'Not found'}")
    if pivot:
        print(f"  ZG = {pivot['ZG']:.2f}, ZD = {pivot['ZD']:.2f}")
    print("="*70)


if __name__ == '__main__':
    main()
