"""
学术因子 - Academic Factors
学术研究中的经典因子
文件路径：backend/app/factors/builtin/academic.py
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


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
        downside_returns = returns.where(returns < target, 0)
        downside_std = downside_returns.rolling(window=period).std()
        
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
        returns = data['close'].pct_change()
        
        market_return = returns.rolling(window=period).mean()
        cov = returns.rolling(window=period).cov(market_return)
        var = market_return.rolling(window=period).var()
        
        return cov / (var + 1e-10)


class ACADEMIC_ALPHA(BaseFactor):
    """Alpha值"""
    name = "ALPHA"
    name_cn = "Alpha值"
    category = "academic"
    subcategory = "excess_return"
    description = "超额收益"
    formula = "Alpha = R_p - (R_f + Beta * (R_m - R_f))"
    source = "Academic"
    source_detail = "Academic"
    
    params = [
        FactorParam("period", 20, "int", 5, 252, "计算周期"),
        FactorParam("risk_free", 0.03, "float", 0, 0.1, "无风险利率")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        rf = self.get_param("risk_free")
        
        returns = data['close'].pct_change()
        market_return = returns.rolling(window=period).mean()
        
        portfolio_mean = returns.rolling(window=period).mean()
        market_mean = market_return
        
        alpha = portfolio_mean - rf - 1.0 * (market_mean - rf)
        
        return alpha


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
    
    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        
        excess_return = returns.rolling(window=period).mean()
        market_return = returns.rolling(window=period).mean()
        cov = returns.rolling(window=period).cov(market_return)
        var = market_return.rolling(window=period).var()
        
        beta = cov / (var + 1e-10)
        
        return excess_return / (beta + 1e-10)


class ACADEMIC_VOLATILITY_10(BaseFactor):
    """10日波动率"""
    name = "VOLATILITY_10"
    name_cn = "10日波动率"
    category = "academic"
    subcategory = "volatility"
    description = "年化收益率标准差"
    formula = "Vol = std(returns) * sqrt(252)"
    source = "Academic"
    source_detail = "Academic"
    
    params = [FactorParam("period", 10, "int", 5, 60, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class ACADEMIC_VOLATILITY_20(BaseFactor):
    """20日波动率"""
    name = "VOLATILITY_20"
    name_cn = "20日波动率"
    category = "academic"
    subcategory = "volatility"
    description = "年化收益率标准差"
    formula = "Vol = std(returns) * sqrt(252)"
    source = "Academic"
    source_detail = "Academic"
    
    params = [FactorParam("period", 20, "int", 10, 120, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class ACADEMIC_VOLATILITY_60(BaseFactor):
    """60日波动率"""
    name = "VOLATILITY_60"
    name_cn = "60日波动率"
    category = "academic"
    subcategory = "volatility"
    description = "年化收益率标准差"
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
            if len(series) < 5:
                return 0
            var_5pct = series.quantile(0.05)
            return series[series <= var_5pct].mean()
        
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
        parkinson_var = hl_ratio.rolling(window=period).mean() ** 2 / (4 * np.log(2))
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
        gk_vol = np.sqrt(gk_var.rolling(window=period).mean()) * np.sqrt(252)
        
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
            if len(series) < 20:
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
    
    params = [FactorParam("period", 252, "int", 60, 504, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        returns = data['close'].pct_change()
        market_return = returns.rolling(window=period).mean()
        
        portfolio_return = returns.rolling(window=period).mean()
        
        cov = returns.rolling(window=period).cov(market_return)
        var = market_return.rolling(window=period).var()
        
        beta = cov / (var + 1e-10)
        alpha = portfolio_return - beta * market_return
        
        return alpha
