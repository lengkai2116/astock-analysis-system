"""FCF yield 截面百分位基准（544-A：批量查询替代逐股 N+1）。

两处调用方共用：valuation_estimator.ValuationEngine.build_fcf_percentile
与 dim7_valuation_engine.Dim7ValuationEngine.build_fcf_percentile。

口径与原逐股实现保持一致：
- total_mv：daily_basic_cache 中该股按 trade_date 升序最后一个非空值（万元）
- free_cashflow：cashflow_cache 中该股按 end_date 降序第一个非空值
- FCF yield = free_cashflow / (total_mv * 1e4) * 100
"""
import bisect
import logging
import math

logger = logging.getLogger(__name__)


def build_fcf_percentile(cache, codes=None, min_samples=200):
    """构建 FCF yield 截面百分位；样本不足返回 None。

    544-A：daily_basic 改为「最新交易日批量 + 缺失股票补查」，避免 660 万行
    全表 GROUP BY/窗口排序（实测 15-17s）；cashflow 仅 7.7 万行，保留窗口查询。
    """
    try:
        code_set = {str(c) for c in codes} if codes is not None else None
        if code_set is not None and not code_set:
            return None

        latest_row = cache._query_shard(
            'daily_basic_cache', "SELECT MAX(trade_date) AS d FROM daily_basic_cache")
        if latest_row is None or latest_row.empty:
            return None
        latest = latest_row.iloc[0]['d']
        if not latest:
            return None

        mv_rows = cache._query_shard(
            'daily_basic_cache',
            "SELECT ts_code, total_mv FROM daily_basic_cache "
            "WHERE trade_date = ? AND total_mv IS NOT NULL", [latest])
        mv_map = {}
        if mv_rows is not None and not mv_rows.empty:
            for _, r in mv_rows.iterrows():
                try:
                    mv = float(r['total_mv'])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(mv) and mv > 0:
                    mv_map[str(r['ts_code'])] = mv

        if code_set is None:
            cand_rows = cache._query_shard(
                'daily_cache',
                "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date = ?", [latest])
            candidates = ({str(c) for c in cand_rows['ts_code'].tolist()}
                          if cand_rows is not None and not cand_rows.empty else set())
        else:
            candidates = code_set
        missing = [c for c in candidates if c not in mv_map]
        if missing:
            ph = ','.join('?' for _ in missing)
            back_rows = cache._query_shard(
                'daily_basic_cache',
                f"SELECT d.ts_code, d.total_mv FROM daily_basic_cache d "
                f"JOIN (SELECT ts_code, MAX(trade_date) AS md FROM daily_basic_cache "
                f"WHERE ts_code IN ({ph}) AND total_mv IS NOT NULL GROUP BY ts_code) x "
                f"ON d.ts_code = x.ts_code AND d.trade_date = x.md "
                f"WHERE d.total_mv IS NOT NULL",
                missing)
            if back_rows is not None and not back_rows.empty:
                for _, r in back_rows.iterrows():
                    try:
                        mv = float(r['total_mv'])
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(mv) and mv > 0:
                        mv_map[str(r['ts_code'])] = mv

        fcf_rows = cache._query_shard(
            'cashflow_cache',
            "SELECT ts_code, free_cashflow FROM ("
            "  SELECT ts_code, free_cashflow, "
            "         ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY end_date DESC) AS rn "
            "  FROM cashflow_cache WHERE free_cashflow IS NOT NULL"
            ") WHERE rn = 1"
        )
        if fcf_rows is None or fcf_rows.empty:
            return None
        fcf_map = {}
        for _, r in fcf_rows.iterrows():
            try:
                fcf = float(r['free_cashflow'])
            except (TypeError, ValueError):
                continue
            if math.isfinite(fcf):
                fcf_map[str(r['ts_code'])] = fcf

        vals = []
        for code, mv in mv_map.items():
            if code_set is not None and code not in code_set:
                continue
            fcf = fcf_map.get(code)
            if fcf is None:
                continue
            vals.append(fcf / (mv * 1e4) * 100)

        if len(vals) < min_samples:
            return None
        vals.sort()
        n = len(vals)
        logger.info("FCF yield 截面基准构建完成（批量）: %s 只", n)
        return lambda v: bisect.bisect_left(vals, v) / n
    except Exception as e:
        logger.warning("FCF 截面基准批量构建失败: %s", e)
        return None
