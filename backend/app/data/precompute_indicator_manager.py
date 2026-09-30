"""
预计算指标管理器
借鉴Vibe-Trading和Qlib的预计算策略
功能说明：
1. 批量预计算所有指标并缓存
2. 从缓存快速获取指标数据
3. 支持预计算触发
"""
import logging

import pandas as pd

from app.indicators import TechnicalIndicatorEngine

logger = logging.getLogger(__name__)
class PrecomputeIndicatorManager:
    """
    预计算指标管理器核心类
    """

    def __init__(self, cache_manager):
        """
        初始化预计算管理器

        Args:
            cache_manager: EnhancedCacheManager实例
        """
        self.cache_manager = cache_manager
        self.engine = TechnicalIndicatorEngine()

    def precompute_all_indicators(self, ts_code: str, df: pd.DataFrame) -> bool:
        """
        预计算所有指标并批量缓存

        Args:
            ts_code: 股票代码
            df: 日线数据DataFrame

        Returns:
            bool: 是否成功完成预计算

        500号批次1（#40）：移除原死参数 `force`（声明「忽略已有缓存」但函数体
        既无缓存查询也无 force 分支，参数从未被使用、docstring 失真）。
        """
        # 414号R6: 阈值从30提高到60，确保MA60/MACD有效
        if len(df) < 60:
            return False

        try:
            # 计算所有指标
            result = self.engine.calculate_all_indicators(df)

            # 写入宽表格式（替代旧 EAV 格式，93% 行数压缩）
            if 'ts_code' not in result.columns:
                result['ts_code'] = ts_code
            self.cache_manager.cache_indicators_wide(ts_code, result)

            return True
        except Exception as e:
            logger.warning(f"预计算指标失败 [{ts_code}]: {e}")
            return False

    # 前瞻收益窗口（交易日）：与 win_rate_cache 表列对齐（5d/10d/20d）
    _WIN_HORIZONS = (5, 10, 20)
    _MIN_SAMPLES = 5      # 行级最少样本（5d），与既有口径一致
    _MIN_SHARPE_N = 5     # sharpe 最少样本数（对齐 strategy_health_monitor）

    @staticmethod
    def _period_stats(returns):
        """单窗口收益统计 → (win_rate, avg_return, sharpe, n)

        sharpe = mean/std(ddof=1) * sqrt(252)（年化，对齐 strategy_health_monitor），
        样本 < _MIN_SHARPE_N 或 std 为 0 时置 0.0。
        """
        n = len(returns)
        if n == 0:
            return 0.0, 0.0, 0.0, 0
        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / n
        avg = sum(returns) / n
        sharpe = 0.0
        if n >= PrecomputeIndicatorManager._MIN_SHARPE_N:
            std = float(pd.Series(returns).std(ddof=1))
            if std > 0:
                sharpe = avg / std * (252 ** 0.5)
        return win_rate, avg, sharpe, n

    def compute_win_rates(self) -> pd.DataFrame:
        """计算策略信号的胜率（基于 strategy_signal_detail + daily_cache）

        424号 P1-2：改解析 signal_json 的 signals 字典，关联 daily_cache 计算前瞻
        收益率，按策略名聚合，输出对齐 win_rate_cache 表结构
        （samples/win_rate_5d/win_rate_10d/win_rate_20d/avg_return_5d/avg_return_20d/
        sharpe_5d/sharpe_20d）。

        500号批次1 修复（A#3 + #36~#39）：
          - **A#3**：原 win_rate_5d/10d/20d、avg_return_5d/20d 均由同一 lookahead=5
            的 returns 计算（10d/20d 与 5d 完全相同）＝假多周期；现**按各自窗口实算**。
          - **#36**：原循环内每信号行 2 次 `_query_shard`（入场/出场价）＝N+1 往返；
            现一次性载入所需窗口的 (ts_code, trade_date)->close 映射后内存索引。
          - **#37**：原仅守 entry_price，exit_price 为 NULL/NaN 时参与减法抛 TypeError；
            现双侧数值/非空校验。
          - **#38**：原 sharpe_5d/20d 硬编码 0.0；现按 mean/std 年化实算。
          - **#39**：原 except 仅 warning 无上下文；现 warning + exc_info，区分故障与合法空。

        Returns:
            pd.DataFrame: 对齐 win_rate_cache 表结构的胜率记录
        """
        try:
            # 1) 读取并展开策略信号（signal_json.signals）
            signal_df = self.cache_manager._query_shard(
                "strategy_signal_detail",
                "SELECT ts_code, trade_date, signal_json "
                "FROM strategy_signal_detail WHERE trade_date IS NOT NULL"
            )
            if signal_df is None or signal_df.empty:
                logger.info("胜率计算: strategy_signal_detail 无数据")
                return pd.DataFrame()

            import json as _json
            sig_rows = []
            sig_dates = set()
            for _, row in signal_df.iterrows():
                ts_code = row['ts_code']
                trade_date = row['trade_date']
                try:
                    sig_obj = _json.loads(row['signal_json']) if row['signal_json'] else {}
                except Exception:
                    continue
                signals = sig_obj.get('signals', {}) or {}
                for strategy, detail in signals.items():
                    if not isinstance(detail, dict):
                        continue
                    sig_rows.append((ts_code, trade_date, strategy))
                if isinstance(signals, dict) and signals:
                    sig_dates.add(trade_date)
            if not sig_rows:
                logger.info("胜率计算: signal_json 无有效信号")
                return pd.DataFrame()

            # 2) 交易日历（用于 idx + horizon 定位前瞻日）
            dates_df = self.cache_manager._query_shard(
                "daily_cache",
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date"
            )
            if dates_df is None or dates_df.empty:
                logger.warning("胜率计算: daily_cache 无交易日，跳过")
                return pd.DataFrame()
            all_dates = sorted(str(d) for d in dates_df['trade_date'].tolist())
            date_to_idx = {d: i for i, d in enumerate(all_dates)}

            # 3) 批量载入收盘价（#36）：仅需 [最早信号日, 最新交易日] 区间，避免 N+1 与全表载入
            min_sig_date = min(sig_dates) if sig_dates else all_dates[0]
            close_df = self.cache_manager._query_shard(
                "daily_cache",
                "SELECT ts_code, trade_date, close FROM daily_cache WHERE trade_date >= ?",
                [min_sig_date]
            )
            if close_df is None or close_df.empty:
                logger.warning("胜率计算: daily_cache 无收盘价，跳过")
                return pd.DataFrame()
            close_map = {
                (r.ts_code, str(r.trade_date)): r.close
                for r in close_df.itertuples(index=False)
                if r.close is not None
            }

            # 4) 按策略聚合（每窗口独立实算）
            by_strategy = {}
            for ts_code, trade_date, strategy in sig_rows:
                by_strategy.setdefault(strategy, []).append((ts_code, trade_date))

            results = []
            for strategy, rows in by_strategy.items():
                rets = {h: [] for h in self._WIN_HORIZONS}
                for ts_code, trade_date in rows:
                    idx = date_to_idx.get(str(trade_date))
                    if idx is None:
                        continue
                    entry = close_map.get((ts_code, str(trade_date)))
                    if entry is None:
                        continue
                    try:
                        entry = float(entry)
                    except (TypeError, ValueError):
                        continue
                    if not (entry > 0):
                        continue
                    for h in self._WIN_HORIZONS:
                        ti = idx + h
                        if ti >= len(all_dates):
                            continue
                        exit_price = close_map.get((ts_code, all_dates[ti]))
                        if exit_price is None:
                            continue
                        try:
                            exit_price = float(exit_price)
                        except (TypeError, ValueError):
                            continue
                        if pd.isna(exit_price):
                            continue
                        rets[h].append((exit_price - entry) / entry)

                n5 = len(rets[5])
                if n5 < self._MIN_SAMPLES:
                    continue
                wr5, avg5, sh5, _ = self._period_stats(rets[5])
                wr10, _, _, _ = self._period_stats(rets[10])
                wr20, avg20, sh20, _ = self._period_stats(rets[20])
                results.append({
                    'signal_type': strategy,
                    'samples': n5,
                    'win_rate_5d': round(wr5, 4),
                    'win_rate_10d': round(wr10, 4),
                    'win_rate_20d': round(wr20, 4),
                    'avg_return_5d': round(avg5, 4),
                    'avg_return_20d': round(avg20, 4),
                    'sharpe_5d': round(sh5, 4),
                    'sharpe_20d': round(sh20, 4),
                })
            if results:
                logger.info(f"胜率计算完成: {len(results)} 种策略类型（窗口 {self._WIN_HORIZONS}）")
            return pd.DataFrame(results) if results else pd.DataFrame()
        except Exception as e:
            # #39：区分「DB/schema 故障」与「合法空」——保留上下文便于定位
            logger.warning(f"胜率计算失败: {e}", exc_info=True)
            return pd.DataFrame()

    def get_win_rates(self) -> pd.DataFrame:
        """获取最近计算的胜率数据（从 win_rate_cache 读取，若无则实时计算）"""
        try:
            # 424号 P1-2：改走分库权威副本（win_rate_cache → snapshot_cache.db）
            cached = self.cache_manager._query_shard(
                "win_rate_cache", "SELECT * FROM win_rate_cache")
            if cached is not None and not cached.empty:
                return cached
        except Exception:
            pass
        # 无缓存 → 实时计算
        return self.compute_win_rates()
