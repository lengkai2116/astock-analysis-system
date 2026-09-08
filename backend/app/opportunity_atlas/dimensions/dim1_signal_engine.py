"""第1维 数据质量门禁层 — 411号方案Phase 3

从分析引擎重写为纯IO层。dim1不再保留任何分析功能和代码。
原分析逻辑（classify_attribute/calc_resonance_score/detect_decay等）
已迁移到JUD层signal_analyzer模块（Phase 2）。

职责：
  1. 预加载dim2-dim7所需的原料数据（data_context）
  2. 数据质量校验
  3. STG闭环补算（对接398号架构）
  4. 返回data_context供dim2-dim7消费

统一接口：evaluate(dims, tags, signals, lifecycle) → {data_context, status_quality}
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Dim1SignalEngine:
    """第1维 数据质量门禁层 — 411号方案Phase 3

    从分析引擎重写为纯IO层。dim1不再保留任何分析功能和代码。
    原分析逻辑已迁移到JUD层signal_analyzer模块（Phase 2）。

    职责：
    1. 预加载dim2-dim7所需的原料数据（data_context）
    2. 数据质量校验
    3. STG闭环补算（对接398号架构）
    4. 返回data_context供dim2-dim7消费
    """

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None, data_context: dict = None) -> dict:
        """数据质量门禁层入口

        411号方案Phase 3：从分析逻辑改为数据准备+质量校验。
        412号方案A1/A2/A3 v3.0：全量加载（ECM表+indicator预计算表+pre_feat_cache ext组）。

        Args:
            dims: 其他维度引擎输出（门禁层不使用，保留签名兼容）
            tags: pre_feat_cache标签
            signals: 策略信号（门禁层不使用，保留签名兼容）
            lifecycle: 生命周期信息（门禁层不使用，保留签名兼容）
            data_context: 外部传入的data_context（门禁层忽略，自行预加载）

        Returns:
            {data_context: dict, status_quality: dict}
            - data_context: 预加载的原料数据集（20+项）
            - status_quality: 数据质量状态标注（含validation_result/completeness_score/missing_tables）
        """
        signals = signals or {}
        lifecycle = lifecycle or {}

        ts_code = tags.get('ts_code', '') if isinstance(tags, dict) else ''

        # 1. 预加载dim2-dim7所需的全部原料数据
        loaded_data = {}
        quality_issues = []

        if ts_code:
            try:
                from app.data import DataManager
                dm = DataManager()

                # ═══ 类别1: ECM原料表（10项）═══

                # daily_cache（dim2/dim3/dim4/dim6需要）
                daily_df = dm.get_cached_daily_data(ts_code)
                if daily_df is not None and not daily_df.empty:
                    loaded_data['daily_df'] = daily_df
                else:
                    quality_issues.append('daily_cache缺失')

                # moneyflow_cache（dim4需要）
                try:
                    mf_df = dm.get_cached_moneyflow(ts_code)
                    if mf_df is not None and not mf_df.empty:
                        loaded_data['moneyflow_df'] = mf_df
                except Exception:
                    quality_issues.append('moneyflow_cache不可用')

                # daily_basic_cache（dim5/dim7需要）
                try:
                    db_df = dm.get_cached_daily_basic(ts_code)
                    if db_df is not None and not db_df.empty:
                        loaded_data['daily_basic_df'] = db_df
                except Exception:
                    quality_issues.append('daily_basic_cache不可用')

                # margin_cache（dim5需要）
                try:
                    margin_df = dm.get_cached_margin(ts_code)
                    if margin_df is not None and not margin_df.empty:
                        loaded_data['margin_df'] = margin_df
                except Exception:
                    pass

                # fina_indicator_cache（dim7需要）
                try:
                    fina_df = dm.get_cached_fina_indicator(ts_code)
                    if fina_df is not None and not fina_df.empty:
                        loaded_data['fina_df'] = fina_df
                except Exception:
                    pass

                # income_cache（dim7需要）
                try:
                    income_df = dm.get_cached_income(ts_code)
                    if income_df is not None and not income_df.empty:
                        loaded_data['income_df'] = income_df
                except Exception:
                    pass

                # balancesheet_cache（dim7需要）
                try:
                    bs_df = dm.get_cached_balancesheet(ts_code)
                    if bs_df is not None and not bs_df.empty:
                        loaded_data['balancesheet_df'] = bs_df
                except Exception:
                    pass

                # cashflow_cache（dim7需要）
                try:
                    cf_df = dm.get_cached_cashflow(ts_code)
                    if cf_df is not None and not cf_df.empty:
                        loaded_data['cashflow_df'] = cf_df
                except Exception:
                    pass

                # stk_holder_cache（未来扩展）
                try:
                    sh_df = dm.get_cached_stk_holder(ts_code)
                    if sh_df is not None and not sh_df.empty:
                        loaded_data['stk_holder_df'] = sh_df
                except Exception:
                    pass

                # lhb_cache（未来扩展）
                try:
                    lhb_df = dm.get_cached_lhb(ts_code)
                    if lhb_df is not None and not lhb_df.empty:
                        loaded_data['lhb_df'] = lhb_df
                except Exception:
                    pass

                # ═══ 类别2: indicator预计算表（3项）═══
                # 通过dm.get_cached_indicators()一次性读取宽表，按列名拆分

                try:
                    indicators_df = dm.get_cached_indicators(ts_code)
                    if indicators_df is not None and not indicators_df.empty:
                        # indicator_ma_df: ma5/10/20/30/60/vol_ma5/vol_ma10
                        ma_cols = [c for c in indicators_df.columns if c.startswith('ma') or c.startswith('vol_ma')]
                        if ma_cols:
                            loaded_data['indicator_ma_df'] = indicators_df[ma_cols].copy()

                        # indicator_macd_df: macd_dif/macd_dea/macd_hist
                        macd_cols = [c for c in indicators_df.columns if c.startswith('macd_')]
                        if macd_cols:
                            loaded_data['indicator_macd_df'] = indicators_df[macd_cols].copy()

                        # indicator_other_df: rsi14/kdj_*/boll_*
                        other_cols = [c for c in indicators_df.columns
                                      if c.startswith('rsi') or c.startswith('kdj') or c.startswith('boll')]
                        if other_cols:
                            loaded_data['indicator_other_df'] = indicators_df[other_cols].copy()
                except Exception:
                    pass

                # ═══ 类别3: pre_feat_cache ext组（9项）═══
                # 通过dm.get_pre_feat()读取嵌套JSON，按组名提取

                try:
                    pre_feat = dm.get_pre_feat(ts_code)
                    if pre_feat and isinstance(pre_feat, dict):
                        ext_groups = [
                            'chip_fund_ext', 'cost_ext', 'volume_ext', 'risk_ext',
                            'fund_5d_ext', 'emotion_ext', 'structure_ext',
                            'market_stats', 'valuation_ext',
                        ]
                        for group in ext_groups:
                            group_data = pre_feat.get(group)
                            if group_data and isinstance(group_data, dict):
                                loaded_data[group] = group_data
                except Exception:
                    pass

                # market_stats 已通过上方 ext_groups 循环从 pre_feat_cache 读取

            except Exception as e:
                quality_issues.append(f'DataManager初始化失败: {e}')

        # 2. 数据质量校验（412号方案A2）
        if loaded_data:
            validation = self._validate(loaded_data, ts_code)
            status_quality = {
                'data_loaded': True,
                'loaded_keys': list(loaded_data.keys()),
                'quality_issues': quality_issues,
                'quality_level': validation['quality_level'],
                'validation_result': validation['validation_result'],
                'completeness_score': validation['completeness_score'],
                'missing_tables': validation['missing_tables'],
            }
            # 3. 数据缺失异步通知（412号方案A3）
            if validation['missing_tables']:
                self._notify_missing_data(ts_code, validation['missing_tables'])
        else:
            status_quality = {
                'data_loaded': False,
                'loaded_keys': [],
                'quality_issues': quality_issues,
                'quality_level': 'failed',
                'validation_result': {},
                'completeness_score': 0.0,
                'missing_tables': [],
            }

        return {
            'data_context': loaded_data if loaded_data else None,
            'status_quality': status_quality,
        }

    def _validate(self, data_context: dict, ts_code: str) -> dict:
        """数据完整性校验（412号方案A2 v3.0）

        Returns:
            {validation_result, completeness_score, missing_tables, quality_level}
        """
        required = ['daily_df']
        optional = [
            # ECM原料表
            'moneyflow_df', 'daily_basic_df', 'margin_df', 'fina_df',
            'income_df', 'balancesheet_df', 'cashflow_df',
            'stk_holder_df', 'lhb_df',
            # indicator预计算表
            'indicator_ma_df', 'indicator_macd_df', 'indicator_other_df',
            # pre_feat_cache ext组
            'chip_fund_ext', 'cost_ext', 'volume_ext', 'risk_ext',
            'fund_5d_ext', 'emotion_ext', 'structure_ext',
            # 市场级统计
            'market_stats',
        ]

        def _is_valid(v):
            """检查值是否有效（非None、非空DataFrame、非空dict）"""
            if v is None:
                return False
            if hasattr(v, 'empty') and v.empty:
                return False
            if isinstance(v, dict) and len(v) == 0:
                return False
            return True

        loaded_keys = [k for k, v in data_context.items() if _is_valid(v)]
        missing = [k for k in required + optional if k not in loaded_keys]

        # 日期对齐检查（仅对有trade_date列的DataFrame检查）
        date_alignment_ok = True
        if 'daily_df' in loaded_keys and hasattr(data_context['daily_df'], 'columns') and 'trade_date' in data_context['daily_df'].columns:
            latest_date = data_context['daily_df']['trade_date'].max()
            for key in ['moneyflow_df', 'daily_basic_df']:
                if key in loaded_keys and hasattr(data_context[key], 'columns') and 'trade_date' in data_context[key].columns:
                    if data_context[key]['trade_date'].max() != latest_date:
                        date_alignment_ok = False

        completeness_score = len(loaded_keys) / (len(required) + len(optional))
        quality_level = 'good' if not missing and date_alignment_ok else 'degraded'
        if not all(k in loaded_keys for k in required):
            quality_level = 'failed'

        return {
            'validation_result': {
                'date_alignment_ok': date_alignment_ok,
                'loaded_count': len(loaded_keys),
                'missing_count': len(missing),
            },
            'completeness_score': round(completeness_score, 4),
            'missing_tables': missing,
            'quality_level': quality_level,
        }

    def _notify_missing_data(self, ts_code: str, missing_tables: list):
        """数据缺失时通知daemon异步补采（412号方案A3 v3.0）

        异步闭环：dim1写sync_requests后立即返回degraded，
        daemon 30s主循环消费sync_requests执行补采，
        下次请求时dim1重新检查数据是否就绪。
        """
        import logging
        logger = logging.getLogger(__name__)
        if not missing_tables:
            return
        try:
            from app.data import DataManager
            dm = DataManager()
            # 映射missing_tables到task_type
            task_map = {
                # ECM原料表
                'daily_df': 'full_daily',
                'moneyflow_df': 'full_moneyflow',
                'daily_basic_df': 'full_basic',
                'fina_df': 'full_daily',
                'income_df': 'full_daily',
                'balancesheet_df': 'full_daily',
                'cashflow_df': 'full_daily',
                'stk_holder_df': 'top10_holders',
                'lhb_df': 'lhb',
                # indicator预计算表 → 触发预计算重跑
                'indicator_ma_df': 'precompute_indicators',
                'indicator_macd_df': 'precompute_indicators',
                'indicator_other_df': 'precompute_indicators',
                # pre_feat_cache ext组 → 触发pre_feat重跑
                'chip_fund_ext': 'precompute_raw',
                'cost_ext': 'precompute_raw',
                'volume_ext': 'precompute_raw',
                'risk_ext': 'precompute_raw',
                'fund_5d_ext': 'precompute_raw',
                'emotion_ext': 'precompute_raw',
                'structure_ext': 'precompute_raw',
                'market_stats': 'precompute_raw',
            }
            for table in missing_tables:
                task_type = task_map.get(table, 'full_daily')
                try:
                    dm.request_data(task_type=task_type, ts_code=ts_code)
                    logger.info(f"dim1通知daemon补采: {task_type} {ts_code}")
                except Exception as e:
                    logger.debug(f"dim1通知daemon跳过 {table}: {e}")
        except Exception as e:
            logger.warning(f"dim1通知daemon失败: {e}")

    def get_data_dependencies(self) -> list:
        """返回本门禁层预加载的数据依赖清单"""
        return [
            'daily_cache — OHLCV行情数据（dim2/dim3/dim4/dim6需要）',
            'moneyflow_cache — 资金流向数据（dim4需要）',
            'daily_basic_cache — 市值/换手率等基础数据（dim5/dim7需要）',
            'margin_cache — 融资融券数据（dim5需要）',
            'fina_indicator_cache — 财务指标数据（dim7需要）',
        ]
