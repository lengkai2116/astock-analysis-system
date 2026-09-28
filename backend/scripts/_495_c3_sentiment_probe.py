"""495号（C3）探针：sentiment_phase=ebb 归属定位

对比三路：
  1. 主源 MarketSentimentService.get_sentiment_phase(最新交易日)（读 sentiment_pool_cache 六段论）
  2. fallback _sentiment_phase_global（读 daily_cache 四档：climax/ebb/ice/ferment）
  3. pre_feat 实际落库 sentiment_phase 分布（确认 5544 只 ebb 来自哪路）

判定：主源 data_available=True 且六段论=ebb → 判定口径合理（涨停 52 家但封板率/板高触发 ebb）；
      主源 data_available=False（池空）→ ebb 来自 fallback daily_cache 口径 → 取数源问题（因层）。
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = os.environ.get('DATA_DIR') or '/Users/kalence/Desktop/01-A股股票分析系统/data'
STOCK_DB = os.path.join(DATA, 'duckdb', 'stock_cache.db')
MARKET_DB = os.path.join(DATA, 'duckdb', 'market_cache.db')


def main():
    # ── 1. sentiment_pool_cache 最新交易日 ──
    conn = sqlite3.connect(STOCK_DB)
    rows = conn.execute("SELECT trade_date, COUNT(*) FROM sentiment_pool_cache "
                        "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 3").fetchall()
    print("sentiment_pool_cache 各交易日行数:", rows)
    if not rows:
        print("!! sentiment_pool_cache 空 —— 主源 data_available=False，ebb 必来自 fallback")
        return
    last = rows[0][0]
    print(f"\n最新交易日: {last}")
    for lt in ('up', 'down', 'zha'):
        n = conn.execute("SELECT COUNT(*) FROM sentiment_pool_cache "
                         "WHERE trade_date=? AND limit_type=?", (last, lt)).fetchone()[0]
        print(f"  limit_type={lt}: {n}")
    up_rows = conn.execute(
        "SELECT consecutive_days, first_seal_time FROM sentiment_pool_cache "
        "WHERE trade_date=? AND limit_type='up' ORDER BY consecutive_days DESC", (last,)).fetchall()
    if up_rows:
        print(f"  涨停最高连板: {up_rows[0][0]}；涨停总数: {len(up_rows)}")
    zha_n = conn.execute("SELECT COUNT(*) FROM sentiment_pool_cache "
                         "WHERE trade_date=? AND limit_type='zha'", (last,)).fetchone()[0]
    up_n = len(up_rows)
    if up_n + zha_n > 0:
        print(f"  封板率(488-2口径 涨停/(涨停+炸板)): {up_n/(up_n+zha_n)*100:.1f}%")
    conn.close()

    # ── 2. 主源六段论（从 market_sentiment_service 代码复算，不实例化 DataManager——
    #    daemon 写锁下初始化会卡死；逻辑与源码逐字一致）──
    up_n2 = len(up_rows)
    max_board = up_rows[0][0] if up_rows else 0
    zha_n2 = zha_n
    if up_n2 > 0 and zha_n2 > 0:
        sealing2 = round(up_n2 / (up_n2 + zha_n2) * 100, 1)
    else:
        sealed2 = sum(1 for _, t in up_rows if t and t != '')
        sealing2 = round(sealed2 / max(up_n2, 1) * 100, 1) if up_n2 > 0 else 0.0
    if up_n2 < 20 and max_board < 3 and sealing2 < 40:
        phase2 = 'ice'
    elif up_n2 < 40 and max_board <= 2 and sealing2 < 50:
        phase2 = 'sprout'
    elif 40 <= up_n2 <= 80 and max_board >= 3 and sealing2 >= 40:
        phase2 = 'ferment'
    elif up_n2 > 80 and sealing2 > 75:
        phase2 = 'climax'
    elif (max_board >= 3 and sealing2 < 50) or (sealing2 < 40 and up_n2 < 40):
        phase2 = 'ebb'
    elif 20 <= up_n2 <= 60 and max_board <= 2:
        phase2 = 'regression'
    else:
        phase2 = 'ferment'
    print(f"\n主源六段论(sentiment_pool_cache {last}): 涨停={up_n2} 最高连板={max_board} "
          f"封板率={sealing2} → phase={phase2!r}（data_available=True）")

    # ── 2b. 09-24（旧 pre_feat 写入日）主源六段论 + fallback ──
    try:
        conn = sqlite3.connect(STOCK_DB)
        up24 = conn.execute("SELECT consecutive_days, first_seal_time FROM sentiment_pool_cache "
                            "WHERE trade_date='2026-09-24' AND limit_type='up' "
                            "ORDER BY consecutive_days DESC").fetchall()
        zha24 = conn.execute("SELECT COUNT(*) FROM sentiment_pool_cache "
                             "WHERE trade_date='2026-09-24' AND limit_type='zha'").fetchone()[0]
        conn.close()
        u24 = len(up24)
        mb24 = up24[0][0] if up24 else 0
        if u24 + zha24 > 0:
            s24 = round(u24 / (u24 + zha24) * 100, 1)
        else:
            s24 = 0.0
        if u24 < 20 and mb24 < 3 and s24 < 40:
            p24 = 'ice'
        elif u24 < 40 and mb24 <= 2 and s24 < 50:
            p24 = 'sprout'
        elif 40 <= u24 <= 80 and mb24 >= 3 and s24 >= 40:
            p24 = 'ferment'
        elif u24 > 80 and s24 > 75:
            p24 = 'climax'
        elif (mb24 >= 3 and s24 < 50) or (s24 < 40 and u24 < 40):
            p24 = 'ebb'
        elif 20 <= u24 <= 60 and mb24 <= 2:
            p24 = 'regression'
        else:
            p24 = 'ferment'
        print(f"09-24 主源六段论: 涨停={u24} 最高连板={mb24} 封板率={s24} → phase={p24!r}")
    except Exception as e:
        print(f"09-24 主源失败: {e}")
    try:
        conn = sqlite3.connect(MARKET_DB)
        lu24 = conn.execute("SELECT COUNT(*) FROM daily_cache "
                            "WHERE trade_date='2026-09-24' AND pct_chg > 9.9").fetchone()[0]
        ld24 = conn.execute("SELECT COUNT(*) FROM daily_cache "
                            "WHERE trade_date='2026-09-24' AND pct_chg < -9.9").fetchone()[0]
        rows24 = conn.execute("SELECT high, close, pct_chg FROM daily_cache "
                              "WHERE trade_date='2026-09-24' AND pct_chg > 5").fetchall()
        t24 = s24x = 0
        for high, close, pct in rows24:
            prev_close = close / (1 + pct / 100)
            if high >= prev_close * 1.099:
                t24 += 1
                if close >= prev_close * 1.099:
                    s24x += 1
        seal24 = round(s24x / t24 * 100, 1) if t24 else 0.0
        conn.close()
        if lu24 > 80 and seal24 > 75:
            fb24 = 'climax'
        elif (lu24 < 40 and seal24 < 40) or ld24 > 20:
            fb24 = 'ebb'
        elif lu24 < 20 and seal24 < 40:
            fb24 = 'ice'
        else:
            fb24 = 'ferment'
        print(f"09-24 fallback daily_cache: limit_up={lu24} limit_down={ld24} "
              f"封板率={seal24} → phase={fb24!r}")
    except Exception as e:
        print(f"09-24 fallback 失败: {e}")

    # ── 3. fallback daily_cache 四档 ──
    try:
        conn = sqlite3.connect(MARKET_DB)
        limit_up = conn.execute(
            "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg > 9.9",
            (last,)).fetchone()[0]
        limit_down = conn.execute(
            "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg < -9.9",
            (last,)).fetchone()[0]
        rows = conn.execute(
            "SELECT high, close, pct_chg FROM daily_cache "
            "WHERE trade_date=? AND pct_chg > 5", (last,)).fetchall()
        touched = sealed = 0
        for high, close, pct in rows:
            prev_close = close / (1 + pct / 100)
            if high >= prev_close * 1.099:
                touched += 1
                if close >= prev_close * 1.099:
                    sealed += 1
        sealing = round(sealed / touched * 100, 1) if touched else 0.0
        conn.close()
        if limit_up > 80 and sealing > 75:
            fb = 'climax'
        elif (limit_up < 40 and sealing < 40) or limit_down > 20:
            fb = 'ebb'
        elif limit_up < 20 and sealing < 40:
            fb = 'ice'
        else:
            fb = 'ferment'
        print(f"fallback daily_cache: limit_up={limit_up} limit_down={limit_down} "
              f"封板率={sealing} → phase={fb!r}")
    except Exception as e:
        print(f"fallback 计算失败: {e}")

    # ── 4. pre_feat 实际落库分布 ──
    try:
        conn = sqlite3.connect(os.path.join(DATA, 'duckdb', 'market_cache.db'))
        sp_rows = conn.execute("SELECT sp, COUNT(*) FROM ("
            "SELECT json_extract(pre_feat, '$.sentiment.sentiment_phase') AS sp "
            "FROM pre_feat_cache) GROUP BY sp ORDER BY COUNT(*) DESC LIMIT 8").fetchall()
        conn.close()
        print(f"\npre_feat 落库 sentiment_phase 分布: {sp_rows}")
    except Exception as e:
        print(f"pre_feat 分布读取失败: {e}")


if __name__ == '__main__':
    main()
