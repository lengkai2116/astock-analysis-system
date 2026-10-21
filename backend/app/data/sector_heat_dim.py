"""532号 RAW-2E：板块热度五维原料装配（只读，不写库）。

输入为既有/批次1 新增表：
  daily_cache（801 指数 + 个股日线）、daily_basic_cache（circ_mv）、
  moneyflow_cache、margin_cache、fund_share_cache、etf_industry_map、
  limit_detail_cache、northbound_flow_cache、relative_strength_cache、stock_sw_industry。
输出：31 个申万一级行业的原始指标行（未打分）；打分由
`app.engine.framework.sector_heat_composite.compute` 完成。
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from pathlib import Path
from statistics import median

import yaml

from app.data.market_universe import is_index_code
from app.data.sw_industry_map import get_sw_industry_map, normalize_code
from app.engine.framework.sector_heat_composite import (
    SW_INDEX_TO_INDUSTRY,
    compute,
    percentile_rank,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / 'config' / 'sector_heat.yaml'


def load_config() -> dict:
    try:
        return yaml.safe_load(_CONFIG_PATH.read_text(encoding='utf-8')) or {}
    except Exception as e:
        logger.warning(f"板块热度配置读取失败，用默认值: {e}")
        return {}


def _f(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _f0(v) -> float:
    x = _f(v)
    return x if x is not None else 0.0


def _ret(closes: list, n: int) -> float | None:
    # n 日收益需 n+1 个收盘点（旧实现 -n-2 多退一天，实为 n+1 日收益）
    if len(closes) < n + 1:
        return None
    a, b = closes[-1], closes[-1 - n]
    if a is None or b in (None, 0):
        return None
    return (a / b - 1.0) * 100.0


def _vp_state(closes: list, amounts: list, pct: list) -> tuple[str | None, float | None, float | None, int | None]:
    if len(closes) < 2 or len(amounts) < 2:
        return None, None, None, None
    base = [a for a in amounts[-6:-1] if a is not None]
    vol_ratio = None
    if base and amounts[-1] is not None:
        avg = sum(base) / len(base)
        if avg > 0:
            vol_ratio = amounts[-1] / avg
    breakout = None
    prev = [c for c in closes[-21:-1] if c is not None]
    if prev and closes[-1] is not None:
        breakout = 1 if closes[-1] >= max(prev) else 0
    last_pct = pct[-1] if pct else None
    if vol_ratio is None:
        return None, None, vol_ratio, breakout
    if vol_ratio >= 1.8 and last_pct is not None and last_pct < -1:
        return '放量下跌', 15.0, vol_ratio, breakout
    if vol_ratio >= 1.8 and breakout == 1:
        return '放量突破', 90.0, vol_ratio, breakout
    if vol_ratio >= 2.0 and breakout == 0 and (last_pct is None or last_pct < 1):
        return '天量滞涨', 25.0, vol_ratio, breakout
    if vol_ratio <= 0.7 and breakout == 0:
        return '缩量回踩', 75.0, vol_ratio, breakout
    if vol_ratio <= 0.5:
        return '地量横盘', 45.0, vol_ratio, breakout
    return '常态', 55.0, vol_ratio, breakout


def _last5_dates(ecm, table: str, end_date: str | None = None) -> list[str]:
    """取截至 end_date 的最近 5 个交易日（end_date=None 取全表最新）。"""
    if end_date:
        df = ecm._query_shard(
            table,
            f"SELECT DISTINCT trade_date FROM {table} WHERE trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT 5", [end_date])
    else:
        df = ecm._query_shard(
            table, f"SELECT DISTINCT trade_date FROM {table} ORDER BY trade_date DESC LIMIT 5")
    if df is None or df.empty:
        return []
    return sorted(str(x) for x in df['trade_date'].tolist())


def build_sector_heat_rows(ecm, target_date: str | None = None) -> tuple[str, list[dict]]:
    """装配并打分；返回 (stat_date, rows)。数据不足返回 ('', [])。

    target_date 指定回算日（YYYY-MM-DD）；所有查询按 <= target_date 截断，
    避免历史回算使用未来数据。None 表示取最新交易日。
    """
    cfg = load_config()
    if target_date:
        dates_df = ecm._query_shard(
            'daily_cache',
            "SELECT DISTINCT trade_date FROM daily_cache WHERE trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT 130", [str(target_date)])
    else:
        dates_df = ecm._query_shard(
            'daily_cache',
            "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 130")
    if dates_df is None or dates_df.empty:
        logger.warning("RAW-2E: daily_cache 无交易日")
        return '', []
    dates = sorted(str(x) for x in dates_df['trade_date'].tolist())
    if len(dates) < 2:
        return '', []
    start, latest = dates[0], dates[-1]

    sw_map = get_sw_industry_map(ecm)
    if not sw_map:
        logger.warning("RAW-2E: 申万一级映射为空")
        return '', []
    industries = sorted(SW_INDEX_TO_INDUSTRY.values())
    code_by_ind = {name: code for code, name in SW_INDEX_TO_INDUSTRY.items()}

    # ── D1：801 指数收益 + HS300 超额 ──────────────────────
    idx = ecm._query_shard(
        'daily_cache',
        "SELECT ts_code, trade_date, close, pct_chg, amount FROM daily_cache "
        "WHERE ts_code LIKE '801%.SI' AND trade_date >= ? AND trade_date <= ?",
        [start, latest])
    series: dict[str, dict] = {}
    if idx is not None and not idx.empty:
        for code, g in idx.groupby('ts_code'):
            g = g.sort_values('trade_date')
            series[str(code)] = {
                'close': [_f(x) for x in g['close'].tolist()],
                'pct': [_f(x) for x in g['pct_chg'].tolist()],
                'amount': [_f(x) for x in g['amount'].tolist()],
            }
    hs = ecm._query_shard(
        'daily_cache',
        "SELECT trade_date, close FROM daily_cache WHERE ts_code='000300.SH' "
        "AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date", [start, latest])
    hs_close = [_f(x) for x in hs['close'].tolist()] if hs is not None and not hs.empty else []
    hs20, hs60 = _ret(hs_close, 20), _ret(hs_close, 60)

    ret20 = {ind: _ret(series.get(code_by_ind[ind], {}).get('close', []), 20) for ind in industries}
    ret60 = {ind: _ret(series.get(code_by_ind[ind], {}).get('close', []), 60) for ind in industries}
    ret120 = {ind: _ret(series.get(code_by_ind[ind], {}).get('close', []), 120) for ind in industries}
    rps20 = percentile_rank([ret20[i] for i in industries])
    rps60 = percentile_rank([ret60[i] for i in industries])
    rps120 = percentile_rank([ret120[i] for i in industries])

    # ── D2：主力/融资/ETF 份额（北向市场级仅背景）──────────
    net = defaultdict(float)
    mf_dates = _last5_dates(ecm, 'moneyflow_cache', latest)
    if mf_dates:
        mf = ecm._query_shard(
            'moneyflow_cache',
            "SELECT ts_code, buy_lg_amount, buy_elg_amount, sell_lg_amount, sell_elg_amount "
            "FROM moneyflow_cache WHERE trade_date >= ? AND trade_date <= ?",
            [mf_dates[0], mf_dates[-1]])
        if mf is not None and not mf.empty:
            for _, r in mf.iterrows():
                if is_index_code(r['ts_code']):
                    continue
                ind = sw_map.get(normalize_code(r['ts_code']))
                if not ind:
                    continue
                net[ind] += (_f0(r['buy_lg_amount']) + _f0(r['buy_elg_amount'])
                             - _f0(r['sell_lg_amount']) - _f0(r['sell_elg_amount']))

    circ = defaultdict(float)
    cb = ecm._query_shard(
        'daily_basic_cache',
        "SELECT ts_code, circ_mv FROM daily_basic_cache WHERE trade_date = ?", [latest])
    if cb is not None and not cb.empty:
        for _, r in cb.iterrows():
            if is_index_code(r['ts_code']):
                continue
            ind = sw_map.get(normalize_code(r['ts_code']))
            if ind:
                circ[ind] += _f0(r['circ_mv'])

    margin_growth: dict[str, float | None] = {}
    mg_dates = _last5_dates(ecm, 'margin_cache', latest)
    if len(mg_dates) >= 2:
        mg = ecm._query_shard(
            'margin_cache',
            "SELECT ts_code, trade_date, rzye FROM margin_cache "
            "WHERE trade_date >= ? AND trade_date <= ?", [mg_dates[0], mg_dates[-1]])
        agg = defaultdict(lambda: defaultdict(float))
        if mg is not None and not mg.empty:
            for _, r in mg.iterrows():
                if is_index_code(r['ts_code']):
                    continue
                ind = sw_map.get(normalize_code(r['ts_code']))
                if ind:
                    agg[ind][str(r['trade_date'])] += _f0(r['rzye'])
        for ind, byd in agg.items():
            a = byd.get(mg_dates[0], 0.0)
            b = byd.get(mg_dates[-1], 0.0)
            if a > 0:
                margin_growth[ind] = (b / a - 1.0) * 100.0

    etf_growth: dict[str, float | None] = {}
    fs_dates = _last5_dates(ecm, 'fund_share_cache', latest)
    if fs_dates:
        em = ecm._query_shard('etf_industry_map', "SELECT ts_code, sw_industry FROM etf_industry_map")
        etf_ind = ({str(r['ts_code']): str(r['sw_industry']) for _, r in em.iterrows()}
                   if em is not None and not em.empty else {})
        if etf_ind:
            fs = ecm._query_shard(
                'fund_share_cache',
                "SELECT ts_code, trade_date, fd_share FROM fund_share_cache "
                "WHERE trade_date >= ? AND trade_date <= ?", [fs_dates[0], fs_dates[-1]])
            agg = defaultdict(lambda: defaultdict(float))
            if fs is not None and not fs.empty:
                for _, r in fs.iterrows():
                    ind = etf_ind.get(str(r['ts_code']))
                    if ind:
                        agg[ind][str(r['trade_date'])] += _f0(r['fd_share'])
            for ind, byd in agg.items():
                a = byd.get(fs_dates[0], 0.0)
                b = byd.get(fs_dates[-1], 0.0)
                if a > 0:
                    etf_growth[ind] = (b / a - 1.0) * 100.0

    north_5d = None
    nb_dates = _last5_dates(ecm, 'northbound_flow_cache', latest)
    if nb_dates:
        nb = ecm._query_shard(
            'northbound_flow_cache',
            "SELECT north_money FROM northbound_flow_cache "
            "WHERE trade_date >= ? AND trade_date <= ?", [nb_dates[0], nb_dates[-1]])
        if nb is not None and not nb.empty:
            north_5d = sum(_f0(x) for x in nb['north_money'].tolist())

    # ── D4/D5：最新日全市场个股（广度、涨停、成交额占比）──
    day = ecm._query_shard(
        'daily_cache',
        "SELECT ts_code, pct_chg, amount FROM daily_cache WHERE trade_date = ?", [latest])
    stock_cnt = defaultdict(int)
    up_cnt = defaultdict(int)
    pct_by_ind = defaultdict(list)
    amount_by_ind = defaultdict(float)
    total_amount = 0.0
    if day is not None and not day.empty:
        for _, r in day.iterrows():
            if is_index_code(r['ts_code']):
                continue
            ind = sw_map.get(normalize_code(r['ts_code']))
            if not ind:
                continue
            amt = _f0(r['amount'])
            pct = _f(r['pct_chg'])
            stock_cnt[ind] += 1
            amount_by_ind[ind] += amt
            total_amount += amt
            if pct is not None:
                pct_by_ind[ind].append(pct)
                if pct > 0:
                    up_cnt[ind] += 1

    u_cnt = defaultdict(int)
    z_cnt = defaultdict(int)
    max_board = defaultdict(int)
    fd_sum = defaultdict(float)
    float_mv_sum = defaultdict(float)
    open_sum = defaultdict(float)
    open_n = defaultdict(int)
    ld = ecm._query_shard(
        'limit_detail_cache',
        "SELECT ts_code, limit_type, limit_times, fd_amount, open_times, float_mv "
        "FROM limit_detail_cache WHERE trade_date = ?", [latest])
    # limit_detail 为「事件行」：某日无涨跌停事件时结果为空，不能据此判为缺数据；
    # 以表内最早日期判断该交易日是否在采集覆盖内（覆盖内的 0 行＝真实 0 事件）。
    limit_min = ''
    try:
        _lm = ecm._query_shard(
            'limit_detail_cache', "SELECT MIN(trade_date) AS d FROM limit_detail_cache")
        if _lm is not None and not _lm.empty:
            limit_min = str(_lm['d'].iloc[0] or '')
    except Exception:
        limit_min = ''
    has_limit_date = bool(limit_min and latest >= limit_min)
    if ld is not None and not ld.empty:
        for _, r in ld.iterrows():
            if is_index_code(r['ts_code']):
                continue
            ind = sw_map.get(normalize_code(r['ts_code']))
            if not ind:
                continue
            lt = str(r['limit_type'] or '')
            if lt == 'U':
                u_cnt[ind] += 1
                max_board[ind] = max(max_board[ind], int(_f0(r['limit_times'])))
            elif lt == 'Z':
                z_cnt[ind] += 1
            fd_sum[ind] += _f0(r['fd_amount'])
            float_mv_sum[ind] += _f0(r['float_mv'])
            ot = _f(r['open_times'])
            if ot is not None:
                open_sum[ind] += ot
                open_n[ind] += 1

    # 板块内高 RPS 占比（个股相对强弱最新 asof，双基准取 000300）
    rps_high = {}
    rsc = ecm._query_shard(
        'relative_strength_cache',
        "SELECT ts_code, rps_20d FROM relative_strength_cache "
        "WHERE asof_date = (SELECT MAX(asof_date) FROM relative_strength_cache "
        "WHERE asof_date <= ?) AND benchmark = '000300.SH'", [latest])
    rsc_cnt = defaultdict(int)
    rsc_high = defaultdict(int)
    if rsc is not None and not rsc.empty:
        for _, r in rsc.iterrows():
            if is_index_code(r['ts_code']):
                continue
            ind = sw_map.get(normalize_code(r['ts_code']))
            if not ind:
                continue
            rps = _f(r['rps_20d'])
            if rps is None:
                continue
            rsc_cnt[ind] += 1
            if rps >= 80:
                rsc_high[ind] += 1
        for ind in rsc_cnt:
            rps_high[ind] = rsc_high[ind] / rsc_cnt[ind] * 100.0

    rows = []
    for i, ind in enumerate(industries):
        s = series.get(code_by_ind[ind], {})
        vp_state, vp_score, vol_ratio, breakout = _vp_state(
            s.get('close', []), s.get('amount', []), s.get('pct', []))
        pcts = pct_by_ind.get(ind, [])
        cnt = stock_cnt.get(ind, 0)
        up_ratio = (up_cnt.get(ind, 0) / cnt) if cnt else None
        med_vs_mean = (median(pcts) - sum(pcts) / len(pcts)) if pcts else None
        u, z = u_cnt.get(ind, 0), z_cnt.get(ind, 0)
        mv = circ.get(ind, 0.0)
        rows.append({
            'industry': ind,
            'ret_20': ret20[ind], 'ret_60': ret60[ind], 'ret_120': ret120[ind],
            'rps_20': rps20[i], 'rps_60': rps60[i], 'rps_120': rps120[i],
            'rps_resonance': sum(1 for v in (rps20[i], rps60[i], rps120[i])
                                 if v is not None and v >= 80),
            'excess_20': (ret20[ind] - hs20) if ret20[ind] is not None and hs20 is not None else None,
            'excess_60': (ret60[ind] - hs60) if ret60[ind] is not None and hs60 is not None else None,
            'main_net_5d': round(net[ind], 1) if net else None,
            'fund_ratio': round(net[ind] / mv * 100, 4) if net and mv > 0 else None,
            'margin_growth_5d': margin_growth.get(ind),
            'north_net_5d': north_5d,
            'etf_share_chg_5d': etf_growth.get(ind),
            'vol_ratio_5d': round(vol_ratio, 3) if vol_ratio is not None else None,
            'breakout_20d': breakout,
            'vp_state': vp_state, 'vp_score': vp_score,
            'limit_up_ratio': round(u / cnt * 100, 3) if (cnt and has_limit_date) else None,
            'zhaban_ratio': (round(z / (u + z) * 100, 3) if (u + z)
                             else (0.0 if has_limit_date else None)),
            'max_board_height': max_board.get(ind, 0) if has_limit_date else None,
            'amount_share': round(amount_by_ind.get(ind, 0.0) / total_amount * 100, 3)
                            if total_amount > 0 else None,
            'fd_amount_ratio': round(fd_sum.get(ind, 0.0) / float_mv_sum[ind] * 100, 4)
                               if float_mv_sum.get(ind, 0.0) > 0 else None,
            'open_times_avg': round(open_sum[ind] / open_n[ind], 2) if open_n.get(ind) else None,
            'up_ratio': round(up_ratio, 4) if up_ratio is not None else None,
            'med_vs_mean': round(med_vs_mean, 3) if med_vs_mean is not None else None,
            'rps_high_ratio': round(rps_high.get(ind), 2) if rps_high.get(ind) is not None else None,
            'index_pct': (s.get('pct') or [None])[-1],
            'calc_version': str(cfg.get('version') or '532.1'),
            'coverage': {
                'd1': ret20[ind] is not None,
                'd2': mv > 0 and bool(net),
                'd3': vp_score is not None,
                'd4': has_limit_date,
                'd5': up_ratio is not None,
                'limit_detail': has_limit_date,
                'rps': rps_high.get(ind) is not None,
                'etf': ind in etf_growth,
                'northbound': bool((cfg.get('enable') or {}).get('northbound', False)),
            },
        })

    return latest, compute(rows, cfg)
