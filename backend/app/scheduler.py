"""
定时任务调度器 - Phase 4.5

功能：每月定时执行全量回测赢率评估，更新缓存

执行方式：
  1. 手动触发: python -m app.scheduler
  2. 应用启动时自动注册（如已配置scheduler）
  3. 外部cron调用: curl /api/v3/backtest/schedule-run
"""
import logging
import traceback
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def run_monthly_backtest():
    """
    月度全量回测任务

    从 StrategyOutput 和 signals 表中读取历史信号数据，
    对每类信号运行赢率评估，结果缓存到 DuckDB。
    """
    try:
        from app import db
        from app.models.strategy import StrategyOutput
        from app.models import Signal as SignalModel
        from app.data import DataManager
        from app.engine.framework.backtest_evidence import (
            SignalWinRateEvaluator,
            SignalClassifier,
        )

        data_mgr = DataManager()
        evaluator = SignalWinRateEvaluator()

        logger.info("=== 开始月度回测赢率评估 ===")

        # 1. 从数据库读取历史信号
        signals = _load_signals()
        if not signals:
            logger.warning("无历史信号数据，跳过回测")
            return

        logger.info(f"读取到 {len(signals)} 条历史信号")

        # 2. 获取相关股票的价格数据
        ts_codes = list(set(s.get('ts_code', '') for s in signals))
        price_data_map = _load_price_data(ts_codes, data_mgr)
        logger.info(f"获取 {len(price_data_map)} 只股票的价格数据")

        # 3. 运行赢率评估
        win_rates = evaluator.evaluate(signals, price_data_map)
        logger.info(f"赢率评估完成: {len(win_rates)} 类信号")

        # 4. 缓存结果
        _cache_win_rates(win_rates)

        # 5. 运行条件概率评估（如果条件数据可用）
        try:
            cond_rates = evaluator.evaluate_with_conditions(
                signals, price_data_map,
                divergence_map=_load_divergence_map(signals),
            )
            _cache_conditional_rates(cond_rates)
            logger.info(f"条件概率评估完成: {len(cond_rates)} 类信号")
        except Exception as e:
            logger.warning(f"条件概率评估跳过: {e}")

        logger.info("=== 月度回测赢率评估完成 ===")

    except Exception as e:
        logger.error(f"月度回测失败: {e}")
        logger.error(traceback.format_exc())


def _load_signals() -> List[Dict]:
    """从数据库加载历史信号"""
    from app import db
    from app.models.strategy import StrategyOutput
    from app.models import Signal as SignalModel

    signals = []

    # 从 StrategyOutput 表读取
    try:
        six_months_ago = datetime.now() - timedelta(days=180)
        records = StrategyOutput.query.filter(
            StrategyOutput.created_at >= six_months_ago
        ).order_by(StrategyOutput.created_at.desc()).limit(5000).all()

        for r in records:
            signals.append({
                'ts_code': r.ts_code,
                'strategy_name': r.strategy_name,
                'signal': r.signal.value if r.signal else 'UNKNOWN',
                'signal_date': r.signal_date.strftime('%Y-%m-%d') if r.signal_date else '',
            })
    except Exception as e:
        logger.warning(f"从 StrategyOutput 读取信号失败: {e}")

    # 从 Signal 表补充
    try:
        six_months_ago = datetime.now() - timedelta(days=180)
        records = SignalModel.query.filter(
            SignalModel.signal_date >= six_months_ago
        ).order_by(SignalModel.signal_date.desc()).limit(5000).all()

        for r in records:
            signals.append({
                'ts_code': r.ts_code,
                'strategy_name': 'chip_strategy',
                'signal': r.signal_type,
                'signal_date': r.signal_date.strftime('%Y-%m-%d') if r.signal_date else '',
            })
    except Exception as e:
        logger.warning(f"从 Signal 表读取信号失败: {e}")

    return signals


def _load_price_data(ts_codes: List[str], data_mgr) -> Dict[str, 'pd.DataFrame']:
    """加载信号对应股票的价格数据"""
    import pandas as pd
    result = {}
    for ts_code in ts_codes[:100]:  # 限制最多100只
        try:
            df = data_mgr.get_cached_daily_data(
                ts_code,
                start_date=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            )
            if not df.empty:
                result[ts_code] = df
        except Exception:
            continue
    return result


def _load_divergence_map(signals: List[Dict]) -> Dict[str, bool]:
    """从信号数据中提取背离信息（简化）"""
    return {}


def _cache_win_rates(win_rates: Dict[str, Dict]):
    """缓存赢率数据到 DuckDB"""
    try:
        from app.data import DataManager
        data_mgr = DataManager()
        import pandas as pd
        records = []
        for sig_type, wr in win_rates.items():
            records.append({
                'signal_type': sig_type,
                'samples': wr.get('samples', 0),
                'win_rate_5d': wr.get('win_rate_5d', 0),
                'win_rate_10d': wr.get('win_rate_10d', 0),
                'win_rate_20d': wr.get('win_rate_20d', 0),
                'avg_return_5d': wr.get('avg_return_5d', 0),
                'avg_return_20d': wr.get('avg_return_20d', 0),
                'sharpe_5d': wr.get('sharpe_5d', 0),
                'sharpe_20d': wr.get('sharpe_20d', 0),
                'evaluated_at': datetime.now().isoformat(),
            })
        if records:
            df = pd.DataFrame(records)
            data_mgr.cache.cache_win_rates(df)
            logger.info(f"已缓存 {len(records)} 条赢率数据")
    except Exception as e:
        logger.warning(f"缓存赢率数据失败: {e}")


def _cache_conditional_rates(cond_rates: Dict[str, object]):
    """缓存条件概率数据"""
    try:
        from app.data import DataManager
        data_mgr = DataManager()
        import pandas as pd
        records = []
        for sig_type, cr in cond_rates.items():
            records.append({
                'signal_type': sig_type,
                'total_samples': cr.total_samples,
                'with_div_samples': cr.with_divergence_samples,
                'with_div_win_rate': cr.with_divergence_win_rate_20d,
                'without_div_samples': cr.without_divergence_samples,
                'without_div_win_rate': cr.without_divergence_win_rate_20d,
                'market_good_samples': cr.market_good_samples,
                'market_good_win_rate': cr.market_good_win_rate_20d,
                'market_poor_samples': cr.market_poor_samples,
                'market_poor_win_rate': cr.market_poor_win_rate_20d,
            })
        if records:
            df = pd.DataFrame(records)
            data_mgr.cache.cache_conditional_win_rates(df)
    except Exception as e:
        logger.warning(f"缓存条件概率数据失败: {e}")


# ==================== 命令行入口 ====================

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    from app import create_app
    app = create_app()
    with app.app_context():
        run_monthly_backtest()
