"""476号：dim7 SIG 截面基准接线 + 分位口径修正 + SSOT 优先测试

覆盖：
  1. dim7.build_composite_percentile 修复（SQL 直读 opportunity_tags_cache，不再 get_tags_batch）
  2. build_fcf_percentile 分布口径（fcf/(mv*1e4)*100，与消费同口径）——dim7 + RAW 双侧
  3. build_potential_percentile_tables val 表改 dev 分布（D4）
  4. _ensure_benchmarks 进程级缓存（构建一次 + 二次命中 + 全失败不缓存）
  5. _compute_valuation SSOT 覆盖（tags composite_rating/valuation_level/deviation 优先，461-2 同构）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest


class _FakeECM:
    """模拟 ECM：_query_shard 按表分派（并模拟 SQL 结果列名）；get_cached_daily_basic/cashflow 返回 df"""

    def __init__(self, shard_data: dict, basic=None, cf=None):
        self._shard = shard_data
        self._basic = basic or {}
        self._cf = cf or {}

    def _query_shard(self, table, sql, params=None):
        df = self._shard.get(table, pd.DataFrame())
        if table == 'daily_cache' and 'MAX(trade_date)' in sql:
            return pd.DataFrame({'d': [df['trade_date'].max()]})
        return df

    def get_cached_daily_basic(self, code):
        return self._basic.get(code, pd.DataFrame())

    def get_cached_cashflow(self, code):
        return self._cf.get(code, pd.DataFrame())


def _mk_basic(code, total_mv):
    return pd.DataFrame({'ts_code': [code], 'total_mv': [total_mv]})


def _mk_cf(code, fcf):
    return pd.DataFrame({'ts_code': [code], 'free_cashflow': [fcf]})


# ══════════════════════════════════════════════════════════
# 1. dim7 build_composite_percentile（SQL 直读修复）
# ══════════════════════════════════════════════════════════

class TestBuildCompositePercentile:
    def test_sql_direct_read_and_neutralized(self, monkeypatch):
        """dim7 侧：不再依赖 dm.get_tags_batch（不存在），SQL 直读 opportunity_tags_cache 可构建"""
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        bank_rows = [{'ts_code': f'60{i:04d}.SH', 'tag_value': 0.4 + i * 0.01} for i in range(60)]
        tech_rows = [{'ts_code': f'30{i:04d}.SZ', 'tag_value': -0.3 + i * 0.007} for i in range(60)]
        rows = bank_rows + tech_rows
        top_val = max(bank_rows, key=lambda r: r['tag_value'])['tag_value']

        def _fake_batch(codes):
            return {c: ('银行' if c.startswith('60') else '电子') for c in codes}

        monkeypatch.setattr(
            'app.data.DataManager.get_stock_industry_batch', staticmethod(_fake_batch))

        engine = mod.Dim7ValuationEngine()
        engine.build_composite_percentile(_FakeECM({'opportunity_tags_cache': pd.DataFrame(rows)}))

        assert engine._comp_percentile is not None, "SQL 直读应构建成功（修复 get_tags_batch 恒失败）"
        bank_mean = engine._industry_mean.get('金融')
        assert bank_mean is not None
        pct = engine._comp_percentile(top_val - bank_mean)
        assert pct > 0.95, f"行业最高 composite 股中性化后应判低估分位 >0.95，实际 {pct:.3f}"


# ══════════════════════════════════════════════════════════
# 2. build_fcf_percentile 分布口径（双侧 /1e4）
# ══════════════════════════════════════════════════════════

class TestBuildFcfPercentile:
    @pytest.mark.parametrize('engine_mod_path,raw_side', [
        ('app.opportunity_atlas.dimensions.dim7_valuation_engine', False),
        ('app.opportunity_atlas.valuation_estimator', True),
    ])
    def test_distribution_aligned_to_consumption(self, engine_mod_path, raw_side, monkeypatch):
        """分布用 fcf/(mv*1e4)*100（与 _anchor_cashflow/compute_tags 同口径）

        构造 205 只：100 只 fcf/(mv*1e4)*100=0.01 + 100 只=1.0 + 5 只=6.0。
        分布排序 [0.01]*100+[1.0]*100+[6.0]*5 → pct(1.0)=100/205、pct(6.0)=200/205；
        修复前分布（fcf/mv*100）=[100]*100+[10000]*100+[60000]*5 → pct(1.0)=0（区分）。
        """
        import importlib
        mod = importlib.import_module(engine_mod_path)
        engine = mod.Dim7ValuationEngine() if hasattr(mod, 'Dim7ValuationEngine') else mod.ValuationEngine()

        n = 205
        codes = [f'X{i:03d}' for i in range(100)] + [f'Y{i:03d}' for i in range(100)] + [f'Z{i:03d}' for i in range(5)]
        basic, cf = {}, {}
        for c in codes:
            prefix = c[0]
            # X→fcf=1e8/mv=1e8 → 0.01；Y→2e10/2e8 → 1.0；Z→6e10/1e8 → 6.0
            basic[c] = _mk_basic(c, 2e8 if prefix == 'Y' else 1e8)
            cf[c] = _mk_cf(c, 1e8 if prefix == 'X' else 2e10 if prefix == 'Y' else 6e10)
        codes_df = pd.DataFrame({'trade_date': ['2026-09-23'] * n, 'ts_code': codes})
        # RAW 侧 build_fcf_percentile 忽略 ecm 参数，用 self._get_dm().cache（treemap_snapshot 取列表）
        shard = {'daily_cache': codes_df, 'treemap_snapshot': codes_df[['ts_code']]}
        ecm = _FakeECM(shard, basic=basic, cf=cf)
        if raw_side:
            class _FakeDM:
                cache = ecm
            monkeypatch.setattr(mod.ValuationEngine, '_get_dm', lambda self: _FakeDM())

        engine.build_fcf_percentile(ecm)
        assert engine._fcf_percentile is not None
        # 修复后 A 的消费口径值 1.0 在分布中位置 = 100/205
        assert engine._fcf_percentile(1.0) == pytest.approx(100 / 205), \
            f"分布应 fcf/(mv*1e4)*100 口径，pct(1.0)=100/205，实际 {engine._fcf_percentile(1.0)}"
        assert engine._fcf_percentile(0.01) == 0.0
        assert engine._fcf_percentile(6.0) == pytest.approx(200 / 205)


# ══════════════════════════════════════════════════════════
# 3. build_potential_percentile_tables：val 表改 dev 分布（D4）
# ══════════════════════════════════════════════════════════

class TestBuildPotentialTables:
    def test_val_table_uses_deviation(self):
        """val 表 = valuation_deviation 截面分布（与 _compute_potential 查询同口径）"""
        from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine

        dev_rows = pd.DataFrame({
            'tag_value': [str(v) for v in [-40, -20, 0, 20, 40]],
        })
        roe_rows = pd.DataFrame({'roe': [5.0, 10.0, 15.0, 20.0, 25.0]})
        ecm = _FakeECM({
            'opportunity_tags_cache': dev_rows,
            'fina_indicator_cache': roe_rows,
        })

        engine = Dim7ValuationEngine()
        engine.build_potential_percentile_tables(ecm)
        assert 'val' in engine._potential_tables and 'earn' in engine._potential_tables
        # dev=20 → 分布 [-40,-20,0,20,40] 中 bisect_left(20)=3 → 3/5
        assert engine._potential_tables['val'](20) == pytest.approx(3 / 5)
        assert engine._potential_tables['val'](-40) == 0.0
        assert engine._potential_tables['val'](40) == pytest.approx(4 / 5)
        # earn 表 = ROE 分位
        assert engine._potential_tables['earn'](15.0) == pytest.approx(2 / 5)


# ══════════════════════════════════════════════════════════
# 4. _ensure_benchmarks 进程级缓存（D2）
# ══════════════════════════════════════════════════════════

class TestEnsureBenchmarks:
    def test_build_once_and_cache(self):
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        dev_rows = pd.DataFrame({'tag_value': ['0', '10', '20']})
        ecm = _FakeECM({'opportunity_tags_cache': dev_rows})

        mod._reset_benchmarks()
        eng1 = mod.Dim7ValuationEngine()
        mod._ensure_benchmarks(eng1, ecm)
        assert eng1._potential_tables.get('val') is not None, "首次应构建 potential val 表"

        # 第二次实例命中缓存（不重建；构建调用计数）
        calls = []
        orig_build = mod.Dim7ValuationEngine.build_potential_percentile_tables
        monkeypatch = pytest.MonkeyPatch()

        def _count(self, ecm):
            calls.append(1)
            return orig_build(self, ecm)

        monkeypatch.setattr(mod.Dim7ValuationEngine, 'build_potential_percentile_tables', _count)
        try:
            eng2 = mod.Dim7ValuationEngine()
            mod._ensure_benchmarks(eng2, ecm)
            assert calls == [], "缓存命中后不应再次构建"
            assert eng2._potential_tables.get('val') is not None, "新实例应共享缓存基准"
        finally:
            monkeypatch.undo()
            mod._reset_benchmarks()

    def test_all_failed_not_cached(self):
        """全部构建失败（ecm 不可用）→ 不缓存，下次重试"""
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        mod._reset_benchmarks()
        eng = mod.Dim7ValuationEngine()
        mod._ensure_benchmarks(eng, None)  # ecm=None → 全部构建失败
        assert mod._BENCHMARKS is None, "全失败不应缓存"
        mod._reset_benchmarks()


# ══════════════════════════════════════════════════════════
# 5. _compute_valuation SSOT 覆盖（D1=C 的 B 部分）
# ══════════════════════════════════════════════════════════

class TestSsotOverrides:
    def _mk(self, monkeypatch, tags):
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        ecm = _FakeECM({}, basic={}, cf={})

        class FakeDM:
            cache = ecm

        monkeypatch.setattr(mod.Dim7ValuationEngine, '_get_dm', lambda self: FakeDM())
        # 数据加载全空 → 实算 composite=0；行业查询不炸
        monkeypatch.setattr('app.data.DataManager.get_stock_industry', lambda self, c: None)
        return mod.Dim7ValuationEngine()

    def test_tags_override_when_present(self, monkeypatch):
        """tags 有 composite_rating/valuation_level/valuation_deviation → 直接采用（RAW 口径）"""
        eng = self._mk(monkeypatch, tags={})
        tags = {
            'composite_rating': '0.8833',
            'valuation_level': 'extreme_low',
            'valuation_deviation': '17.7',
            'fina_health': 'pass',
        }
        val = eng._compute_valuation('300750.SZ', eng._get_dm().cache, tags=tags)
        assert val['valuation_level'] == 'extreme_low', "level 应 SSOT 读 tags"
        assert val['valuation_deviation'] == 17.7, "deviation 应 SSOT 读 tags"
        assert val['composite_rating'] == pytest.approx(0.8833), "composite 应 SSOT 读 tags"

    def test_fallback_when_tags_missing(self, monkeypatch):
        """tags 缺失 → 走实算判定（兜底不炸，合理值）"""
        eng = self._mk(monkeypatch, tags={})
        val = eng._compute_valuation('300750.SZ', eng._get_dm().cache, tags={})
        # 数据空 → 各锚 0 → composite=0 → level=fair（绝对阈值 -0.3<=0<=0.3）
        assert val['valuation_level'] == 'fair'
        assert val['composite_rating'] == pytest.approx(0.0, abs=0.01)
        assert val['valuation_deviation'] == pytest.approx(0.0)
