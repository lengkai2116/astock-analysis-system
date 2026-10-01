"""
学术因子 - Academic Factors
学术研究中的经典因子
文件路径：backend/app/factors/builtin/academic.py
"""
import logging
from datetime import datetime

import numpy as np
import pandas as pd

from ..base import BaseFactor, FactorParam

logger = logging.getLogger(__name__)

# ── 502批次3 #R2：BETA 系真实市场基准（HS300）＋R_f（国债）──
# 原实现用个股自身收益当市场基准（market 代理自引用）→ BETA/TREYNOR/CAPM_ALPHA
# 非真实现、ALPHA 恒 0。此处接 438 号已闭环的 HS300 日线（benchmark_service），
# 模块级按日缓存避免重复读库；基准缺失/异常 → None（调用方返回 NaN，426 无源守卫）。
_MKT_RET_CACHE: dict = {'day': None, 'ret': None}


def _get_market_return():
    """HS300 日线收益率序列（索引 trade_date 字符串）；失败/缺失返回 None"""
    today = datetime.now().date()
    if _MKT_RET_CACHE['day'] == today and _MKT_RET_CACHE['ret'] is not None:
        return _MKT_RET_CACHE['ret']
    try:
        from app.services.benchmark_service import BenchmarkIndex, BenchmarkService
        df = BenchmarkService().get_index_daily(BenchmarkIndex.HS300)
        if df is None or df.empty or 'close' not in df.columns:
            return None
        ret = df.set_index(df['trade_date'].astype(str))['close'].astype(float).pct_change()
        _MKT_RET_CACHE['day'] = today
        _MKT_RET_CACHE['ret'] = ret
        return ret
    except Exception as e:  # 基准缺失不假造（426 P0-1 语义）
        logger.warning("BETA 系市场基准获取失败，返回 None: %s", e)
        return None


def _resolve_rf(risk_free):
    """R_f：参数未传（None）→ 取系统统一国债收益率 CN_10Y_BOND_YIELD_PCT（百分数→小数）"""
    if risk_free is None:
        from app.opportunity_atlas.valuation_estimator import CN_10Y_BOND_YIELD_PCT
        return float(CN_10Y_BOND_YIELD_PCT) / 100.0
    return float(risk_free)


def _align_market(data, period):
    """对齐个股与 HS300 收益率 → (stock_ret, mkt_ret, dates, 原索引)

    返回 None 表示市场基准不可用（调用方应输出 NaN 序列，不假造）。
    """
    mkt = _get_market_return()
    if mkt is None:
        return None
    if 'trade_date' in data.columns:
        dates = pd.Series(data['trade_date'].astype(str), index=data.index)
    else:
        dates = pd.Series(data.index.astype(str), index=data.index)
    stock = pd.Series(data['close'].astype(float).pct_change().values, index=dates.values)
    aligned = pd.concat([stock.rename('stock'), mkt.rename('mkt')], axis=1, join='inner')
    aligned = aligned.dropna()
    return aligned, dates, data.index


class ACADEMIC_SKEWNESS(BaseFactor):
    """收益率偏度"""
    name = "SKEWNESS"
    name_cn = "收益率偏度"
    category = "academic"
    subcategory = "distribution"
    description = "收益率分布的偏度"
    formula = "Skewness = E[(R - mean)^3] / std^3"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).skew()


class ACADEMIC_KURTOSIS(BaseFactor):
    """收益率峰度"""
    name = "KURTOSIS"
    name_cn = "收益率峰度"
    category = "academic"
    subcategory = "distribution"
    description = "收益率分布的峰度"
    formula = "Kurtosis = E[(R - mean)^4] / std^4 - 3"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).kurt()


class ACADEMIC_MAX_DRAWDOWN(BaseFactor):
    """历史最大回撤"""
    name = "MAX_DRAWDOWN"
    name_cn = "历史最大回撤"
    category = "academic"
    subcategory = "risk"
    description = "过去N日的最大回撤"
    formula = "MaxDD = max((Peak - Trough) / Peak)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")

        def max_dd(series):
            if len(series) < 2:
                return 0
            cummax = series.cummax()
            drawdown = (cummax - series) / cummax
            return drawdown.max()

        return data['close'].rolling(window=period).apply(max_dd, raw=True)


class ACADEMIC_SORTINO(BaseFactor):
    """Sortino比率因子"""
    name = "SORTINO"
    name_cn = "Sortino比率"
    category = "academic"
    subcategory = "risk_adjusted"
    description = "下行风险调整收益"
    formula = "Sortino = (mean - r_f) / downside_std"
    source = "Academic"
    source_detail = "Academic"

    params = [
        FactorParam("period", 20, "int", 5, 252, "计算周期"),
        FactorParam("target_return", 0.0, "float", -0.1, 0.1, "目标收益")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        target = self.get_param("target_return")

        returns = data['close'].pct_change()
        # 502批次2 #R3：下行偏差修复——原 `returns.where(<target, 0).std()` 把 0 值计入散布
        # 系统性低估；正确为负超额收益 RMS：sqrt(mean(clip(r-target, upper=0)²))
        downside = (returns - target).clip(upper=0)
        downside_std = np.sqrt((downside ** 2).rolling(window=period).mean())

        mean_return = returns.rolling(window=period).mean()

        return (mean_return - target) / (downside_std + 1e-10)


class ACADEMIC_CALMAR(BaseFactor):
    """Calmar比率"""
    name = "CALMAR"
    name_cn = "Calmar比率"
    category = "academic"
    subcategory = "risk_adjusted"
    description = "年化收益与最大回撤的比值"
    formula = "Calmar = annual_return / max_drawdown"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 252, "int", 20, 504, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")

        returns = data['close'].pct_change()
        annual_return = returns.rolling(window=period).mean() * 252

        def max_dd(series):
            if len(series) < 2:
                return 0
            cummax = series.cummax()
            drawdown = (cummax - series) / cummax
            return drawdown.max()

        max_drawdown = data['close'].rolling(window=period).apply(max_dd, raw=True)

        return annual_return / (max_drawdown + 1e-10)


class ACADEMIC_OMEGA(BaseFactor):
    """Omega比率"""
    name = "OMEGA"
    name_cn = "Omega比率"
    category = "academic"
    subcategory = "risk_adjusted"
    description = "收益与损失的比率"
    formula = "Omega = sum(gains) / sum(losses)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")

        returns = data['close'].pct_change()

        def omega_ratio(series):
            if len(series) < 2:
                return 0
            gains = series[series > 0].sum()
            losses = abs(series[series < 0].sum())
            return gains / (losses + 1e-10)

        return returns.rolling(window=period).apply(omega_ratio, raw=True)


class ACADEMIC_INFORMATION_RATIO(BaseFactor):
    """信息比率"""
    name = "INFO_RATIO"
    name_cn = "信息比率"
    category = "academic"
    subcategory = "relative_performance"
    description = "超额收益与跟踪误差的比值"
    formula = "IR = active_return / tracking_error"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()

        active_return = returns.rolling(window=period).mean()
        tracking_error = returns.rolling(window=period).std()

        return active_return / (tracking_error + 1e-10)


class ACADEMIC_BETA(BaseFactor):
    """Beta值"""
    name = "BETA"
    name_cn = "Beta值"
    category = "academic"
    subcategory = "market_sensitivity"
    description = "相对于市场的敏感度"
    formula = "Beta = Cov(R, R_m) / Var(R_m)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        # 502批次3 #R2：真实市场基准 Beta = Cov(R_i, R_m)/Var(R_m)（HS300）
        aligned = _align_market(data, period)
        if aligned is None:
            return pd.Series(np.nan, index=data.index)
        aligned_df, dates, data_index = aligned
        if len(aligned_df) < period + 1:
            return pd.Series(np.nan, index=data.index)
        cov = aligned_df['stock'].rolling(window=period).cov(aligned_df['mkt'])
        var = aligned_df['mkt'].rolling(window=period).var()
        beta = cov / (var + 1e-10)
        return pd.Series(beta.values, index=aligned_df.index).reindex(dates).set_axis(data_index)


class ACADEMIC_ALPHA(BaseFactor):
    """Alpha值"""
    name = "ALPHA"
    name_cn = "Alpha值"
    category = "academic"
    subcategory = "excess_return"
    description = "超额收益（502批次3 #R2：接真实市场基准 HS300 + R_f；原自引用恒 0）"
    formula = "Alpha = R_p - (R_f + Beta * (R_m - R_f))"
    source = "Academic"
    source_detail = "Academic"

    params = [
        FactorParam("period", 20, "int", 5, 252, "计算周期"),
        FactorParam("risk_free", None, "float", 0, 0.1, "无风险利率（None=取系统国债收益率）")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        rf = _resolve_rf(self.get_param("risk_free"))
        aligned = _align_market(data, period)
        if aligned is None:
            return pd.Series(np.nan, index=data.index)
        aligned_df, dates, data_index = aligned
        if len(aligned_df) < period + 1:
            return pd.Series(np.nan, index=data.index)
        cov = aligned_df['stock'].rolling(window=period).cov(aligned_df['mkt'])
        var = aligned_df['mkt'].rolling(window=period).var()
        beta = cov / (var + 1e-10)
        rp = aligned_df['stock'].rolling(window=period).mean()
        rm = aligned_df['mkt'].rolling(window=period).mean()
        alpha = rp - rf - beta * (rm - rf)
        return pd.Series(alpha.values, index=aligned_df.index).reindex(dates).set_axis(data_index)


class ACADEMIC_TREYNOR(BaseFactor):
    """Treynor比率"""
    name = "TREYNOR"
    name_cn = "Treynor比率"
    category = "academic"
    subcategory = "risk_adjusted"
    description = "超额收益与Beta的比值"
    formula = "Treynor = (R_p - R_f) / Beta"
    source = "Academic"
    source_detail = "Academic"

    params = [
        FactorParam("period", 20, "int", 5, 252, "计算周期"),
        FactorParam("risk_free", None, "float", 0, 0.1, "无风险利率（None=取系统国债收益率）")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        rf = _resolve_rf(self.get_param("risk_free"))
        # 502批次3 #R2：真实市场基准 Treynor = (R_p - R_f)/Beta（原自引用近似 + 缺 R_f）
        aligned = _align_market(data, period)
        if aligned is None:
            return pd.Series(np.nan, index=data.index)
        aligned_df, dates, data_index = aligned
        if len(aligned_df) < period + 1:
            return pd.Series(np.nan, index=data.index)
        cov = aligned_df['stock'].rolling(window=period).cov(aligned_df['mkt'])
        var = aligned_df['mkt'].rolling(window=period).var()
        beta = cov / (var + 1e-10)
        excess = aligned_df['stock'].rolling(window=period).mean() - rf
        treynor = excess / (beta + 1e-10)
        return pd.Series(treynor.values, index=aligned_df.index).reindex(dates).set_axis(data_index)


class ACADEMIC_VOLATILITY_10(BaseFactor):
    """10日波动率（学术版）"""
    name = "ACADEMIC_VOLATILITY_10"
    name_cn = "10日波动率（学术）"
    category = "academic"
    subcategory = "volatility"
    description = "年化收益率标准差（学术版）"
    formula = "Vol = std(returns) * sqrt(252)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 10, "int", 5, 60, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class ACADEMIC_VOLATILITY_20(BaseFactor):
    """20日波动率（学术版）"""
    name = "ACADEMIC_VOLATILITY_20"
    name_cn = "20日波动率（学术）"
    category = "academic"
    subcategory = "volatility"
    description = "年化收益率标准差（学术版）"
    formula = "Vol = std(returns) * sqrt(252)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 10, 120, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class ACADEMIC_VOLATILITY_60(BaseFactor):
    """60日波动率（学术版）"""
    name = "ACADEMIC_VOLATILITY_60"
    name_cn = "60日波动率（学术）"
    category = "academic"
    subcategory = "volatility"
    description = "年化收益率标准差（学术版）"
    formula = "Vol = std(returns) * sqrt(252)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 60, "int", 30, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class ACADEMIC_CVAR(BaseFactor):
    """条件VaR"""
    name = "CVAR"
    name_cn = "条件VaR"
    category = "academic"
    subcategory = "risk"
    description = "条件风险价值"
    formula = "CVaR = E[R | R < VaR]"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()

        def cvar(series):
            # 501 #R43：raw=True 传 numpy 数组——原 `series.quantile` 在 ndarray 上
            # 不存在（AttributeError，因子从未跑通）；改 np.percentile + 空/退化显式 NaN
            if len(series) == 0:
                return np.nan
            var_5pct = np.percentile(series, 5)
            tail = series[series <= var_5pct]
            return float(tail.mean()) if len(tail) > 0 else np.nan

        return returns.rolling(window=period).apply(cvar, raw=True)


class ACADEMIC_NORMALIZED_VOL(BaseFactor):
    """标准化波动率"""
    name = "NORM_VOL"
    name_cn = "标准化波动率"
    category = "academic"
    subcategory = "volatility"
    description = "波动率除以平均绝对收益率"
    formula = "NormVol = std(returns) / mean(abs(returns))"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()

        vol = returns.rolling(window=period).std()
        mean_abs = returns.abs().rolling(window=period).mean()

        return vol / (mean_abs + 1e-10)


class ACADEMIC_PARKINSON(BaseFactor):
    """Parkinson波动率"""
    name = "PARKINSON"
    name_cn = "Parkinson波动率"
    category = "academic"
    subcategory = "volatility"
    description = "使用高低价的波动率估计"
    formula = "Parkinson = sqrt((1/(4*ln2)) * mean((ln(H/L))^2))"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")

        hl_ratio = np.log(data['high'] / data['low'])
        # 502批次2 #R45：括号位修复——先平方再 rolling mean（原 `mean**2` 在 Jensen 不等式下低估）
        parkinson_var = (hl_ratio ** 2).rolling(window=period).mean() / (4 * np.log(2))
        parkinson_vol = np.sqrt(parkinson_var) * np.sqrt(252)

        return parkinson_vol


class ACADEMIC_GARMAN_KLASS(BaseFactor):
    """Garman-Klass波动率"""
    name = "GARMAN_KLASS"
    name_cn = "Garman-Klass波动率"
    category = "academic"
    subcategory = "volatility"
    description = "更精确的波动率估计"
    formula = "GK = sqrt(0.5 * mean(ln(H/L))^2 - (2*ln(2)-1) * mean(ln(C/O))^2)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")

        hl = np.log(data['high'] / data['low'])
        co = np.log(data['close'] / data['open'])

        gk_var = 0.5 * hl ** 2 - (2 * np.log(2) - 1) * co ** 2
        # 501 #R22：GK 方差可负（co² 项无下界）→ sqrt 负值静默 NaN；clamp 至 0 后再开方
        gk_mean = gk_var.rolling(window=period).mean().clip(lower=0)
        gk_vol = np.sqrt(gk_mean) * np.sqrt(252)

        return gk_vol


class ACADEMIC_ROLLING_CORR(BaseFactor):
    """滚动相关性"""
    name = "ROLL_CORR"
    name_cn = "滚动相关性"
    category = "academic"
    subcategory = "correlation"
    description = "价格与成交量的滚动相关性"
    formula = "Corr = rolling_corr(close, volume)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).corr(data['vol'])


class ACADEMIC_HURST(BaseFactor):
    """Hurst指数"""
    name = "HURST"
    name_cn = "Hurst指数"
    category = "academic"
    subcategory = "market_dynamics"
    description = "衡量时间序列的自相似性"
    formula = "Hurst = log(R/S) / log(N)"
    source = "Academic"
    source_detail = "Academic"

    params = [FactorParam("period", 100, "int", 50, 500, "计算周期")]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()

        def hurst_exp(series):
            # 501 #R44：守卫基准对齐 period（原硬编码 20 与 period min=50 脱节——
            # rolling 满窗口 series 长度恒=period，硬编码 20 永不触发、语义失真）
            if len(series) < period:
                return 0.5
            n = len(series)
            mean_val = series.mean()
            cumdev = (series - mean_val).cumsum()
            r = cumdev.max() - cumdev.min()
            s = series.std()
            if s < 1e-10:
                return 0.5
            return np.log(r/s) / np.log(n)

        return returns.rolling(window=period).apply(hurst_exp, raw=True)


class ACADEMIC_CAPM_ALPHA(BaseFactor):
    """CAPM Alpha"""
    name = "CAPM_ALPHA"
    name_cn = "CAPM Alpha"
    category = "academic"
    subcategory = "pricing"
    description = "CAPM模型Alpha"
    formula = "Alpha = R_p - R_f - Beta * (R_m - R_f)"
    source = "Academic"
    source_detail = "Fama-French"

    params = [
        FactorParam("period", 252, "int", 60, 504, "计算周期"),
        FactorParam("risk_free", None, "float", 0, 0.1, "无风险利率（None=取系统国债收益率）")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        rf = _resolve_rf(self.get_param("risk_free"))
        # 502批次3 #R2：真实市场基准 CAPM Alpha = R_p - R_f - Beta*(R_m - R_f)
        aligned = _align_market(data, period)
        if aligned is None:
            return pd.Series(np.nan, index=data.index)
        aligned_df, dates, data_index = aligned
        if len(aligned_df) < period + 1:
            return pd.Series(np.nan, index=data.index)
        cov = aligned_df['stock'].rolling(window=period).cov(aligned_df['mkt'])
        var = aligned_df['mkt'].rolling(window=period).var()
        beta = cov / (var + 1e-10)
        rp = aligned_df['stock'].rolling(window=period).mean()
        rm = aligned_df['mkt'].rolling(window=period).mean()
        alpha = rp - rf - beta * (rm - rf)
        return pd.Series(alpha.values, index=aligned_df.index).reindex(dates).set_axis(data_index)
