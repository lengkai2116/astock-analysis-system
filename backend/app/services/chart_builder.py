"""
ChartBuilder — 缠论 K 线结构可视化制图系统

直接生成 lightweight-charts JS 自包含 HTML（不依赖 lightweight-charts-python 桌面端），
输出为独立 HTML 文件，离线可交互，支持缩放/平移/十字光标。

使用示例：
    from app.services.chart_builder import ChartBuilder
    from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
    from app.data import DataManager

    dm = DataManager()
    df = dm.get_cached_daily_data('301448.SZ')
    cl = ChanlunAnalyzer(config={})
    result = cl.analyze(df)

    builder = ChartBuilder(title='301448.SZ 日线缠论结构')
    builder.set_klines(df)
    builder.add_fractals(result['fractals'])
    builder.add_strokes(result['strokes'])
    builder.add_zhongshu(result['zhongshu'])
    builder.add_buy_sell(result['buy_points'], result['sell_points'])
    html = builder.to_html()          # 返回 HTML 字符串
    builder.save('chart.html')        # 或保存为文件
"""

import json
import logging
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# TradingView Lightweight Charts JS 版本
LW_VERSION = '4.2.1'


def _fmt_date(d) -> str:
    """格式化日期为 YYYY-MM-DD，无效值返回空字符串"""
    if d is None:
        return ''
    try:
        if isinstance(d, datetime):
            return d.strftime('%Y-%m-%d')
        s = str(d).strip().lower()
        if s in ('', 'nan', 'none', 'nat', 'null'):
            return ''
        return s[:10]
    except Exception:
        return ''


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class ChartBuilder:
    """缠论 K 线结构图构建器

    直接生成 lightweight-charts JS 自包含 HTML。
    不依赖 lightweight-charts-python 桌面端渲染。
    分型/笔/中枢/买卖点四层叠加标注。
    """

    # ── 配色 ──
    COLOR_UP = '#22c55e'
    COLOR_DOWN = '#ef4444'
    COLOR_FX_TOP = '#f59e0b'
    COLOR_FX_BOTTOM = '#3b82f6'
    COLOR_BI_UP = '#60a5fa'
    COLOR_BI_DOWN = '#f87171'
    COLOR_ZS_TOP = 'rgba(99,102,241,0.6)'
    COLOR_ZS_BOTTOM = 'rgba(99,102,241,0.6)'
    COLOR_ZS_FILL = 'rgba(99,102,241,0.10)'
    COLOR_BUY = '#22c55e'
    COLOR_SELL = '#ef4444'

    def __init__(self, title: str = '缠论结构分析'):
        self.title = title
        self._klines_json = '[]'
        self._fractals = []
        self._strokes = []
        self._zhongshu = []
        self._buy = []
        self._sell = []

    # ── 数据接口 ─────────────────────────────────────

    def set_klines(self, df) -> None:
        """设置 K 线数据"""
        import pandas as pd
        # 兼容日线(trade_date)和分钟线(trade_time)两种列名，trade_time优先
        rename = {'trade_time': 'time', 'trade_date': 'time', 'vol': 'volume'}
        for old, new in rename.items():
            if old in df.columns and new not in df.columns:
                df = df.rename(columns={old: new})
        cols = ['time', 'open', 'high', 'low', 'close', 'volume']
        available = [c for c in cols if c in df.columns]
        subset = df[available].copy()
        if 'time' in subset.columns:
            subset['time'] = subset['time'].apply(
                lambda x: str(x)[:10] if pd.notna(x) and str(x).strip() != 'nan' else '')
        self._klines_json = subset.to_json(orient='records', date_format='iso')

    def add_fractals(self, fractals: List) -> None:
        """添加分型数据"""
        for f in fractals:
            if not hasattr(f, 'date') or not f.date:
                continue
            self._fractals.append({
                'time': _fmt_date(f.date),
                'type': getattr(f, 'type', ''),
                'price': _safe_float(getattr(f, 'price', 0)),
            })

    def add_strokes(self, strokes: List) -> None:
        """添加笔数据（跳过日期无效的笔）"""
        for s in strokes:
            sd = _fmt_date(s.start_date)
            ed = _fmt_date(s.end_date)
            if not sd or not ed:
                continue
            self._strokes.append({
                'start_date': sd,
                'end_date': ed,
                'start_price': _safe_float(s.start_price),
                'end_price': _safe_float(s.end_price),
                'direction': s.direction,
            })

    def add_zhongshu(self, zhongshu_list: List) -> None:
        """添加中枢数据（跳过日期无效的中枢）"""
        for zs in zhongshu_list:
            sd = _fmt_date(zs.start_date)
            ed = _fmt_date(zs.end_date)
            if not sd or not ed:
                continue
            self._zhongshu.append({
                'start_date': sd,
                'end_date': ed,
                'high': _safe_float(zs.high),
                'low': _safe_float(zs.low),
                'center': _safe_float(
                    getattr(zs, 'center', (zs.high + zs.low) / 2)),
            })

    def add_buy_sell(self, buy_points: List, sell_points: List) -> None:
        """添加买卖点数据"""
        for bp in buy_points:
            d = _fmt_date(getattr(bp, 'date', None))
            if d:
                self._buy.append(d)
        for sp in sell_points:
            d = _fmt_date(getattr(sp, 'date', None))
            if d:
                self._sell.append(d)

    # ── HTML 生成 ────────────────────────────────────

    def _build_series_config(self) -> str:
        """生成 lightweight-charts 系列配置 JS"""
        parts = []

        # K 线数据
        parts.append(f'const klineData = {self._klines_json};')

        # 分型标记
        fx_json = json.dumps(self._fractals)
        parts.append(f'const fxData = {fx_json};')

        # 笔数据
        st_json = json.dumps(self._strokes)
        parts.append(f'const biData = {st_json};')

        # 中枢数据
        zs_json = json.dumps(self._zhongshu)
        parts.append(f'const zsData = {zs_json};')

        # 买卖点
        buy_json = json.dumps(self._buy)
        sell_json = json.dumps(self._sell)
        parts.append(f'const buyData = {buy_json};')
        parts.append(f'const sellData = {sell_json};')

        return '\n'.join(parts)

    def _build_render_js(self) -> str:
        """生成渲染 JS 代码"""
        return f'''
        // 创建图表
        const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
            layout: {{
                background: {{ type: 'solid', color: '#0f0f1a' }},
                textColor: '#d1d5db',
                fontSize: 12,
            }},
            crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
            grid: {{
                vertLines: {{ visible: false }},
                horzLines: {{ color: 'rgba(255,255,255,0.05)' }},
            }},
            watermark: {{
                visible: true,
                text: '{self.title}',
                color: 'rgba(180,180,240,0.3)',
                fontSize: 28,
            }},
            width: 1200,
            height: 600,
        }});

        // K 线
        const candleSeries = chart.addCandlestickSeries({{
            upColor: '{self.COLOR_UP}',
            downColor: '{self.COLOR_DOWN}',
            borderUpColor: '{self.COLOR_UP}',
            borderDownColor: '{self.COLOR_DOWN}',
            wickUpColor: '#4ade80',
            wickDownColor: '#f87171',
        }});
        candleSeries.setData(klineData);

        // 分型 + 买卖点（合并为单一标记集）
        const markers = [];

        fxData.forEach(f => {{
            markers.push({{
                time: f.time,
                position: f.type === 'top' ? 'above' : 'below',
                shape: f.type === 'top' ? 'arrowDown' : 'arrowUp',
                color: f.type === 'top' ? '{self.COLOR_FX_TOP}' : '{self.COLOR_FX_BOTTOM}',
            }});
        }});
        buyData.forEach(d => {{
            markers.push({{ time: d, position: 'below', shape: 'arrowUp', color: '{self.COLOR_BUY}', text: 'B' }});
        }});
        sellData.forEach(d => {{
            markers.push({{ time: d, position: 'above', shape: 'arrowDown', color: '{self.COLOR_SELL}', text: 'S' }});
        }});
        candleSeries.setMarkers(markers);

        // 笔（每笔一条独立线）
        biData.forEach((bi, i) => {{
            const color = bi.direction === 'up' ? '{self.COLOR_BI_UP}' : '{self.COLOR_BI_DOWN}';
            const lineSeries = chart.addLineSeries({{
                color: color,
                lineWidth: 2,
                lastValueVisible: false,
                priceLineVisible: false,
            }});
            lineSeries.setData([
                {{ time: bi.start_date, value: bi.start_price }},
                {{ time: bi.end_date, value: bi.end_price }},
            ]);
        }});

        // 中枢（上下沿水平线）
        zsData.forEach(zs => {{
            // 上沿
            chart.addLineSeries({{
                color: '{self.COLOR_ZS_TOP}',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                lastValueVisible: true,
                priceLineVisible: false,
            }}).setData([
                {{ time: zs.start_date, value: zs.high }},
                {{ time: zs.end_date, value: zs.high }},
            ]);
            // 下沿
            chart.addLineSeries({{
                color: '{self.COLOR_ZS_BOTTOM}',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                lastValueVisible: true,
                priceLineVisible: false,
            }}).setData([
                {{ time: zs.start_date, value: zs.low }},
                {{ time: zs.end_date, value: zs.low }},
            ]);
        }});

        // 买卖点
        buyData.forEach(d => {{
            candleSeries.setMarkers([{{ time: d, position: 'below', shape: 'arrowUp', color: '{self.COLOR_BUY}', text: 'B' }}]);
        }});
        sellData.forEach(d => {{
            candleSeries.setMarkers([{{ time: d, position: 'above', shape: 'arrowDown', color: '{self.COLOR_SELL}', text: 'S' }}]);
        }});

        chart.timeScale().fitContent();
        '''

    def _build_html(self) -> str:
        """组装完整 HTML"""
        series_config = self._build_series_config()
        render_js = self._build_render_js()

        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{self.title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0f0f1a; display: flex; justify-content: center; padding: 20px; }}
  #chart {{ width: 1200px; height: 600px; border-radius: 8px; overflow: hidden; }}
</style>
<script src="https://unpkg.com/lightweight-charts@{LW_VERSION}/dist/lightweight-charts.standalone.production.js"></script>
</head>
<body>
<div id="chart"></div>
<script>
{series_config}
{render_js}
</script>
</body>
</html>'''

    # ── 输出 ─────────────────────────────────────────

    def to_html(self) -> str:
        """返回独立 HTML 字符串"""
        return self._build_html()

    def save(self, path: str) -> str:
        """保存为 HTML 文件

        Args:
            path: 输出文件路径

        Returns:
            实际写入的文件路径
        """
        html = self._build_html()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f'缠论结构图已保存: {path}')
        return path
