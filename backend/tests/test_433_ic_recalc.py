"""433号 批次2 单测：IC 重估（earn-only）逻辑 + 落盘原子性 + daemon 月度钩子幂等

覆盖（DB-free，自包含临时隔离，不碰开发态基准库）：
  - recompute_ic_weights 分支：earn IC 正→ok 上调 / 负→no_signal 保留 / 数据不足→insufficient_data / 6 键归一化
  - save_ic_weights：原子写（tmp+os.replace）+ last_recalc 幂等时间戳
  - write_ic_report：ic_report.json 落盘（含 status/新旧权重）
  - run_monthly_ic_recalc 门面：ok 落盘 / no_signal 不覆盖但写报告
  - data_daemon._maybe_monthly_ic_recalc：本月已算→跳过；上月→触发一次
"""
import json
import os

import numpy as np
import pandas as pd
import pytest
from app.opportunity_atlas import potential_engine as pe

PERIODS = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]


class FakeECM:
    """合成分库数据：roe 与未来收益正相关 → earn IC 正（可翻转 / 调弱为不显著）"""

    def __init__(self, seed=1, n_stock=200, n_day=160, invert=False, drift_scale=1.0):
        rng = np.random.default_rng(seed)
        self.codes = [f"{i:06d}.SZ" for i in range(n_stock)]
        self.dates = pd.bdate_range("2026-01-01", periods=n_day).strftime("%Y-%m-%d").tolist()
        self.roe_base = pd.Series(rng.normal(8, 4, n_stock), index=self.codes)
        self.close = {}
        for i, c in enumerate(self.codes):
            base = 10 + i * 0.01
            drift = self.roe_base[c] * 0.002 * drift_scale
            prices = base * (1 + np.cumsum(rng.normal(drift, 0.02, n_day)))
            self.close[c] = prices[::-1] if invert else prices

    def _query_shard(self, table, sql, params=None):
        if "DISTINCT trade_date" in sql:
            return pd.DataFrame({"trade_date": self.dates})
        if table == "daily_cache":
            rows = [(c, d, float(self.close[c][j]))
                    for c in self.codes for j, d in enumerate(self.dates)]
            df = pd.DataFrame(rows, columns=["ts_code", "trade_date", "close"])
            if params:
                d0, d1 = params
                df = df[(df["trade_date"] >= d0) & (df["trade_date"] <= d1)]
            return df
        if table == "fina_indicator_cache":
            rows = [(c, p, float(self.roe_base[c] + 0.5))
                    for c in self.codes for p in PERIODS]
            return pd.DataFrame(rows, columns=["ts_code", "end_date", "roe"])
        return pd.DataFrame()


# ── 1. recompute_ic_weights 分支 ──

def test_earn_ic_positive_ok():
    res = pe.recompute_ic_weights(FakeECM(), lookback_days=160, horizon=20)
    assert res["status"] == "ok"
    assert set(res["weights"]) == set(pe.DIM_WEIGHTS)
    assert abs(sum(res["weights"].values()) - 1.0) < 0.01
    assert res["weights"]["earn"] > pe.DIM_WEIGHTS["earn"], "正 IC 应上调 earn 权重"
    assert res["ic_report"]["earn"]["ic_mean"] > 0
    assert res["ic_report"]["window"]["n_sections"] >= 3


def test_earn_ic_negative_no_signal():
    res = pe.recompute_ic_weights(FakeECM(invert=True), lookback_days=160, horizon=20)
    assert res["status"] == "no_signal"
    assert res["weights"] == dict(pe.DIM_WEIGHTS), "非正 IC 应保留配置权重（不劣化）"
    assert res["ic_report"]["earn"]["ic_mean"] <= 0


def test_insufficient_data_when_days_short():
    ecm = FakeECM()
    ecm.dates = ecm.dates[:20]  # 交易日不足 30
    res = pe.recompute_ic_weights(ecm, lookback_days=40, horizon=20)
    assert res["status"] == "insufficient_data"
    assert res["weights"] == dict(pe.DIM_WEIGHTS)


def test_weights_normalized_six_keys():
    res = pe.recompute_ic_weights(FakeECM(), lookback_days=160, horizon=20)
    assert set(res["weights"]) == set(pe.DIM_WEIGHTS)
    assert abs(sum(res["weights"].values()) - 1.0) < 1e-3


def test_earn_ic_weak_positive_not_significant_no_signal():
    """W1（433 §3.6）：earn IC 为正但统计不显著 → no_signal 保留配置权重"""
    res = pe.recompute_ic_weights(FakeECM(drift_scale=0.0), lookback_days=160, horizon=20)
    assert res["status"] == "no_signal"
    assert res["ic_report"]["earn"]["significant"] is False
    assert res["weights"] == dict(pe.DIM_WEIGHTS), "不显著正 IC 不得调整权重"


def test_sig_crit_high_forces_no_signal():
    """W1 门槛参数生效：强正 IC 在超高门槛下也判不显著"""
    res = pe.recompute_ic_weights(FakeECM(), lookback_days=160, horizon=20, sig_t_crit=50.0)
    assert res["status"] == "no_signal"
    assert res["ic_report"]["earn"]["significant"] is False


def test_smoothing_uses_prev_earn():
    """W4（433 §3.6）：earn 权重平滑——earn_new = α·w_ic + (1-α)·prev_earn，介于两者之间"""
    res_no_prev = pe.recompute_ic_weights(FakeECM(), lookback_days=160, horizon=20)
    assert res_no_prev["status"] == "ok"
    w_none = res_no_prev["weights"]["earn"]
    # prev_earn 低于当前计算值 → 平滑后 earn 被拉低（仍高于 prev）
    res_low = pe.recompute_ic_weights(FakeECM(), lookback_days=160, horizon=20, prev_earn=0.10)
    assert res_low["status"] == "ok"
    assert 0.10 < res_low["weights"]["earn"] < w_none
    # prev_earn 高于当前计算值 → 平滑后 earn 被拉高（仍低于 prev）
    res_high = pe.recompute_ic_weights(FakeECM(), lookback_days=160, horizon=20, prev_earn=0.45)
    assert res_high["status"] == "ok"
    assert w_none < res_high["weights"]["earn"] < 0.45
    assert abs(sum(res_high["weights"].values()) - 1.0) < 1e-3


# ── 2. save_ic_weights：原子写 + last_recalc ──

def test_save_ic_weights_atomic_with_last_recalc(tmp_path):
    old_file = pe.IC_WEIGHTS_FILE
    pe.IC_WEIGHTS_FILE = str(tmp_path / "ic_weights.json")
    try:
        pe.save_ic_weights(dict(pe.DIM_WEIGHTS))
        with open(pe.IC_WEIGHTS_FILE, encoding="utf-8") as f:
            payload = json.load(f)
        assert all(k in payload for k in pe.DIM_WEIGHTS)
        assert "last_recalc" in payload, "应带 last_recalc 幂等时间戳"
        assert not os.path.exists(pe.IC_WEIGHTS_FILE + ".tmp"), "原子写后 tmp 应清理"
    finally:
        pe.IC_WEIGHTS_FILE = old_file


def test_write_ic_report(tmp_path):
    old_file = pe.IC_WEIGHTS_FILE
    pe.IC_WEIGHTS_FILE = str(tmp_path / "ic_weights.json")
    try:
        pe.write_ic_report({"status": "ok", "earn": {"ic_mean": 0.02}})
        report_file = tmp_path / "ic_weights_report.json"
        assert report_file.exists()
        with open(report_file, encoding="utf-8") as f:
            r = json.load(f)
        assert r["status"] == "ok"
    finally:
        pe.IC_WEIGHTS_FILE = old_file


# ── 3. run_monthly_ic_recalc 门面 ──

def test_run_monthly_ok_persists(tmp_path):
    old_file = pe.IC_WEIGHTS_FILE
    pe.IC_WEIGHTS_FILE = str(tmp_path / "ic_weights.json")
    try:
        res = pe.run_monthly_ic_recalc(FakeECM(), data_dir=str(tmp_path))
        assert res["status"] == "ok"
        # 落盘 + last_recalc
        with open(pe.IC_WEIGHTS_FILE, encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["earn"] != pe.DIM_WEIGHTS["earn"] or "last_recalc" in payload
        assert "last_recalc" in payload
        # ic_report 落盘
        assert (tmp_path / "ic_weights_report.json").exists()
    finally:
        pe.IC_WEIGHTS_FILE = old_file


def test_run_monthly_no_signal_not_overwrite(tmp_path):
    old_file = pe.IC_WEIGHTS_FILE
    pe.IC_WEIGHTS_FILE = str(tmp_path / "ic_weights.json")
    try:
        res = pe.run_monthly_ic_recalc(FakeECM(invert=True), data_dir=str(tmp_path))
        assert res["status"] == "no_signal"
        # no_signal：不覆盖权重文件（无 last_recalc 时间戳写入）
        assert not os.path.exists(pe.IC_WEIGHTS_FILE)
        # 但写 ic_report 监控证据
        assert (tmp_path / "ic_weights_report.json").exists()
    finally:
        pe.IC_WEIGHTS_FILE = old_file


# ── 4. data_daemon 月度钩子幂等 ──

def test_monthly_hook_skips_when_current_month_done(tmp_path, monkeypatch):
    from datetime import datetime

    import data_daemon
    # 构造「本月已算」状态：last_recalc 月份 == 当前月
    now_m = datetime.now().strftime("%Y-%m")
    wfile = tmp_path / "ic_weights.json"
    wfile.write_text(json.dumps({**pe.DIM_WEIGHTS, "last_recalc": f"{now_m}-01T00:00:00"}),
                     encoding="utf-8")
    called = []
    monkeypatch.setattr(data_daemon, "_run_with_timeout",
                        lambda f, timeout_sec=30, desc="": called.append(desc) or f())
    data_daemon._maybe_monthly_ic_recalc(str(tmp_path))
    assert called == [], "本月已算 → 不应触发重算"


def test_monthly_hook_skips_when_report_recalc_at_current_month(tmp_path, monkeypatch):
    """433 批次4：no_signal 不写 last_recalc，须以 report.recalc_at 兜底幂等（防每 tick 重算）"""
    from datetime import datetime

    import data_daemon
    now_m = datetime.now().strftime("%Y-%m")
    # ic_weights.json 无 last_recalc（no_signal 未落盘），仅 report 带本月 recalc_at
    report_file = tmp_path / "ic_weights_report.json"
    report_file.write_text(json.dumps({"status": "no_signal", "recalc_at": f"{now_m}-05T12:00:00"}),
                           encoding="utf-8")
    called = []
    monkeypatch.setattr(data_daemon, "_run_with_timeout",
                        lambda f, timeout_sec=30, desc="": called.append(desc) or f())
    data_daemon._maybe_monthly_ic_recalc(str(tmp_path))
    assert called == [], "report 本月已算 → 不应触发重算（即使 ic_weights.json 无 last_recalc）"


def test_monthly_hook_triggers_when_last_month(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    import data_daemon
    # 构造「上月已算」状态：last_recalc 月份 == 上月
    last_m = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    wfile = tmp_path / "ic_weights.json"
    wfile.write_text(json.dumps({**pe.DIM_WEIGHTS, "last_recalc": f"{last_m}-15T10:00:00"}),
                     encoding="utf-8")
    called = []
    monkeypatch.setattr(data_daemon, "_ecm", FakeECM())
    monkeypatch.setattr(data_daemon, "_run_with_timeout",
                        lambda f, timeout_sec=30, desc="": called.append(desc) or f())
    data_daemon._maybe_monthly_ic_recalc(str(tmp_path))
    assert called, "上月已算 → 本月应触发一次重算"
