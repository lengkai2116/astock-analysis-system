"""
组合对称交叉验证 (Combinatorial Symmetric Cross-Validation, CSCV)

实现 Bailey & Lopez de Prado (2015) 提出的 CSCV 方法，
用于估计概率性回测过拟合 (Probabilistic Backtest Overfitting, PBO)。

参考论文:
  "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting,
   and Non-Normality" — Bailey & Lopez de Prado (2014)
  "The Probability of Backtest Overfitting" — Bailey et al. (2015)

核心逻辑:
  1. 将收益率序列划分为 S 个连续块
  2. 生成 C(S, S/2) 种训练/测试集组合
  3. 每种组合下: 训练集选最优参数 → 测试集评估
  4. PBO = 训练集最优参数在测试集中排名低于中位数的概率
"""

from __future__ import annotations

import itertools
from typing import Any, Callable, Dict, List, Optional

import numpy as np


# ── 辅助函数 ──────────────────────────────────────────────────────────


def calculate_sharpe(returns: np.ndarray, annual_factor: float = 252.0) -> float:
    """
    计算年化夏普比率。

    Parameters
    ----------
    returns : np.ndarray
        日收益率序列。
    annual_factor : float, default=252.0
        年化因子（日频数据默认 252）。

    Returns
    -------
    float
        年化夏普比率。若收益率序列长度 < 2 或标准差为零，返回 0.0。
    """
    if len(returns) < 2:
        return 0.0
    std = np.std(returns, ddof=1)
    if std == 0.0 or np.isnan(std):
        return 0.0
    mean = np.mean(returns)
    return (mean / std) * np.sqrt(annual_factor)


# ── 主类 ──────────────────────────────────────────────────────────────


class CSCVValidator:
    """
    Combinatorial Symmetric Cross-Validation (CSCV) 验证器。

    用于评估策略参数优化中的过拟合风险，输出 PBO 指标。

    Parameters
    ----------
    n_splits : int, default=6
        时间序列划分块数 S。必须为偶数，且 >= 4。
    random_state : int, optional, default=42
        随机种子，用于结果复现。
    """

    def __init__(self, n_splits: int = 6, random_state: int = 42) -> None:
        if n_splits < 4:
            raise ValueError("n_splits 必须 >= 4")
        if n_splits % 2 != 0:
            raise ValueError("n_splits 必须为偶数（标准 CSCV 要求 S/2 为整数）")
        self.n_splits = n_splits
        self.random_state = random_state
        np.random.seed(random_state)

    # ── 公共方法 ──────────────────────────────────────────────────────

    def compute_pbo(self, sharpe_matrix: np.ndarray) -> Dict[str, Any]:
        """
        基于夏普比率矩阵计算 PBO。

        Parameters
        ----------
        sharpe_matrix : np.ndarray, shape (n_configs, n_splits)
            sharpe_matrix[i][j] 表示第 i 个参数配置在第 j 个测试块上的夏普比率。
            矩阵必须为非空且行列数符合要求。

        Returns
        -------
        Dict[str, Any]
            包含以下字段:
            - pbo: float, 概率性回测过拟合指标
            - is_robust: bool, 是否鲁棒
            - n_configs: int, 参数配置数
            - n_splits: int, 划分块数
            - n_combos: int, 实际计算的组合数
            - rank_matrix: np.ndarray, shape (n_combos, n_configs), 各组合下各参数配置的排名
            - best_rank_oos: np.ndarray, shape (n_combos,), 各组合下最优参数的 OOS 排名
            - rank_below_median: int, 最优参数排名低于中位数的次数
        """
        n_configs, n_splits = sharpe_matrix.shape
        if n_configs < 1 or n_splits < 2:
            return self._empty_result(n_configs, n_splits)

        if n_splits != self.n_splits:
            self.n_splits = n_splits  # 自适应

        train_size = self.n_splits // 2
        split_indices = list(range(self.n_splits))
        combos = list(itertools.combinations(split_indices, train_size))
        n_combos = len(combos)

        rank_matrix = np.zeros((n_combos, n_configs), dtype=float)
        best_rank_oos = np.zeros(n_combos, dtype=float)

        for c_idx, train_splits in enumerate(combos):
            train_set = set(train_splits)
            test_splits = [i for i in split_indices if i not in train_set]

            # 训练集: 取各配置在训练块上的平均夏普 → 选最优配置
            train_sharpes = np.mean(sharpe_matrix[:, list(train_set)], axis=1)
            best_config = int(np.argmax(train_sharpes))

            # 测试集: 取各配置在测试块上的平均夏普 → 排秩（1=最好）
            test_sharpes = np.mean(sharpe_matrix[:, test_splits], axis=1)
            # 夏普越高，秩越小（rank=1 最高）
            ranks = np.argsort(np.argsort(-test_sharpes)) + 1
            rank_matrix[c_idx, :] = ranks

            # 记录最优配置在测试集中的排名
            best_rank_oos[c_idx] = ranks[best_config]

        # PBO = 最优配置在测试集中排名低于中位数的比例
        median_rank = (n_configs + 1) / 2.0
        rank_below_median = int(np.sum(best_rank_oos > median_rank))
        pbo = rank_below_median / n_combos if n_combos > 0 else 1.0

        return {
            "pbo": float(pbo),
            "is_robust": self.is_robust(pbo),
            "n_configs": n_configs,
            "n_splits": self.n_splits,
            "n_combos": n_combos,
            "rank_matrix": rank_matrix,
            "best_rank_oos": best_rank_oos,
            "rank_below_median": rank_below_median,
        }

    def evaluate(
        self,
        returns: np.ndarray,
        param_configs: List[Any],
        param_func: Callable[[np.ndarray, Any], float],
    ) -> Dict[str, Any]:
        """
        便捷包装器: 直接传入收益率序列和参数配置列表，自动完成 CSCV 分析。

        Parameters
        ----------
        returns : np.ndarray, shape (n_obs,)
            全样本收益率序列。
        param_configs : List[Any]
            参数配置列表，每个元素会传给 param_func 作为第二个参数。
        param_func : Callable[[np.ndarray, Any], float]
            接收 (returns_subset, param) 返回夏普比率的函数。

        Returns
        -------
        Dict[str, Any]
            包含 compute_pbo 返回的所有字段，额外包含 returns_shape。
        """
        n_obs = len(returns)
        if n_obs < self.n_splits:
            return {
                "pbo": 1.0,
                "is_robust": False,
                "n_configs": len(param_configs),
                "n_splits": self.n_splits,
                "n_combos": 0,
                "error": "收益率序列长度不足以进行划分",
                "returns_shape": returns.shape,
            }

        splits = np.array_split(returns, self.n_splits)
        n_configs = len(param_configs)
        sharpe_matrix = np.zeros((n_configs, self.n_splits), dtype=float)

        for j in range(self.n_splits):
            for i, param in enumerate(param_configs):
                sharpe_matrix[i, j] = param_func(splits[j], param)

        result = self.compute_pbo(sharpe_matrix)
        result["returns_shape"] = returns.shape
        return result

    @staticmethod
    def is_robust(pbo: float, threshold: float = 0.05) -> bool:
        """
        判断 PBO 是否在可接受阈值内。

        Parameters
        ----------
        pbo : float
            概率性回测过拟合指标。
        threshold : float, default=0.05
            阈值。PBO < threshold 认为策略鲁棒。

        Returns
        -------
        bool
            True 表示策略鲁棒，过拟合风险低。
        """
        return pbo < threshold

    @staticmethod
    def simulate_backtest_sharpes(n_params: int, n_splits: int = 6) -> np.ndarray:
        """
        生成用于测试的合成夏普比率矩阵。

        前一半参数配置为"真实有效"（夏普较高），后一半为"随机噪音"（夏普通近零）。
        用于验证 PBO 计算逻辑。

        Parameters
        ----------
        n_params : int
            参数配置数量。
        n_splits : int, default=6
            划分块数。

        Returns
        -------
        np.ndarray, shape (n_params, n_splits)
            合成的夏普比率矩阵。
        """
        np.random.seed(42)
        sharpe_matrix = np.zeros((n_params, n_splits), dtype=float)

        half = max(1, n_params // 2)

        # 前一半: 真实有效策略，各块间有一定波动
        for i in range(half):
            base_sharpe = np.random.uniform(0.8, 1.5)
            noise = np.random.normal(0, 0.15, n_splits)
            sharpe_matrix[i, :] = base_sharpe + noise

        # 后一半: 噪音策略，夏普通近零
        for i in range(half, n_params):
            sharpe_matrix[i, :] = np.random.normal(0, 0.2, n_splits)

        return sharpe_matrix

    # ── 内部方法 ──────────────────────────────────────────────────────

    def _empty_result(self, n_configs: int, n_splits: int) -> Dict[str, Any]:
        """返回空结果（用于边缘情况）。"""
        return {
            "pbo": 1.0,
            "is_robust": False,
            "n_configs": n_configs,
            "n_splits": n_splits,
            "n_combos": 0,
            "rank_matrix": np.empty((0, max(n_configs, 1))),
            "best_rank_oos": np.empty(0),
            "rank_below_median": 0,
            "error": "数据不足: 参数配置或划分块数不足",
        }


# ── 模块级便捷函数 ─────────────────────────────────────────────────────


def compute_cscv_pbo(
    returns: np.ndarray,
    param_configs: List[Any],
    param_func: Callable[[np.ndarray, Any], float],
    n_splits: int = 6,
) -> Dict[str, Any]:
    """
    一键计算 CSCV PBO 的模块级函数。

    等价于:
        validator = CSCVValidator(n_splits=n_splits)
        return validator.evaluate(returns, param_configs, param_func)

    Parameters
    ----------
    returns : np.ndarray
        全样本收益率序列。
    param_configs : List[Any]
        参数配置列表。
    param_func : Callable[[np.ndarray, Any], float]
        接收 (returns_subset, param) 返回夏普比率的函数。
    n_splits : int, default=6
        划分块数。

    Returns
    -------
    Dict[str, Any]
        CSCV 分析结果字典。
    """
    validator = CSCVValidator(n_splits=n_splits)
    return validator.evaluate(returns, param_configs, param_func)
