"""491号（R4-①②）：注册信号链修复——volume_breakout 触发 + signals 落库列

用户 2026-09-27 拍板 B+C：
- **B**：`_detect_registered_signals` 的 volume_breakout 分支原读已废弃容器
  `signals['量价分析策略']`（411 Phase 1 后 signal_json.signals 设计上为空 → 恒失效）。
  改读活 tags，按 334 §5.2「引用现有标签」：pattern_signal 含突破 + 量比≥1.5 + 突破前高
  （用 shared_support_resistance.signal_days=站上前60日高点后天数）。
- **C**：`status_snapshot` 表无 signals 列 → `_assemble`/`evaluate` 产出的 hits 被落库层丢弃。
  补 DDL 列 + 迁移 + 自建表写入 + 归档（17 列）。

本文件用纯函数调用 + 源码断言（零 DB 副作用，与 test_321 同模式）。
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import data_daemon  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

logging.disable(logging.CRITICAL)


def _hits(tags: dict) -> set:
    """纯函数调用（_detect_registered_signals 不依赖 self）"""
    return {h['type'] for h in StatusEngine._detect_registered_signals(None, tags, {})}


# ══════════════════════════════════════════════════════════
# B：volume_breakout 触发（334 §5.2 完整条件，活 tags 供给）
# ══════════════════════════════════════════════════════════

class TestVolumeBreakout:

    def test_fires_when_all_conditions_met(self):
        tags = {'pattern_signal': '平台放量突破', 'volume_ratio': 2.0, 'signal_days': 3}
        assert 'volume_breakout' in _hits(tags)

    def test_requires_volume_ratio(self):
        tags = {'pattern_signal': '平台放量突破', 'volume_ratio': 1.2, 'signal_days': 3}
        assert 'volume_breakout' not in _hits(tags)

    def test_requires_signal_days(self):
        """未站上前60日高点（signal_days=0/None）→ 不算突破"""
        tags = {'pattern_signal': '平台放量突破', 'volume_ratio': 2.0, 'signal_days': 0}
        assert 'volume_breakout' not in _hits(tags)
        tags2 = {'pattern_signal': '平台放量突破', 'volume_ratio': 2.0}
        assert 'volume_breakout' not in _hits(tags2)

    def test_requires_breakout_pattern(self):
        tags = {'pattern_signal': 'W底', 'volume_ratio': 3.0, 'signal_days': 5}
        assert 'volume_breakout' not in _hits(tags)

    def test_string_values_tolerated(self):
        """tags 值可能为字符串（pre_feat JSON 反序列化）→ 应可转换，不抛"""
        tags = {'pattern_signal': '低位横盘突破', 'volume_ratio': '2.0', 'signal_days': '3'}
        assert 'volume_breakout' in _hits(tags)

    def test_bad_values_no_crash(self):
        tags = {'pattern_signal': '突破缺口', 'volume_ratio': 'abc', 'signal_days': 'x'}
        assert 'volume_breakout' not in _hits(tags)

    def test_no_longer_reads_deprecated_container(self):
        """回归守卫：废弃容器 signals['量价分析策略'] 不再触发（411 Phase 1 后恒空）"""
        tags = {}
        old_style = {'量价分析策略': {'signal_label': '放量突破'}}
        assert 'volume_breakout' not in {
            h['type'] for h in StatusEngine._detect_registered_signals(None, tags, old_style)}

    def test_other_rules_unaffected(self):
        assert 'chan_third_buy' in _hits({'buy_sell_point': '三买(1)'})
        assert 'ma_bullish' in _hits({'ma_alignment': '多头'})
        assert 'platform_breakout' in _hits({'pattern_signal': '平台放量突破'})
        assert 'pattern_up' in _hits({'pattern_signal': '平台放量突破'})
        assert _hits({'pattern_signal': 'none'}) == set()


# ══════════════════════════════════════════════════════════
# C：signals 落库列链路（DDL + 迁移 + 写入 + 归档）
# ══════════════════════════════════════════════════════════

class TestSignalsColumnChain:

    def test_build_status_snapshot_new_table_has_signals(self):
        src = inspect.getsource(data_daemon._build_status_snapshot)
        assert 'signals TEXT' in src, '_NEW 建表缺 signals 列'

    def test_build_status_snapshot_insert_writes_signals(self):
        src = inspect.getsource(data_daemon._build_status_snapshot)
        assert "row.get('signals')" in src, 'INSERT 未写入 signals（hits 被丢弃）'

    def test_history_archive_has_signals_and_migration(self):
        src = inspect.getsource(data_daemon)
        assert 'signals TEXT' in src
        assert 'ALTER TABLE status_snapshot_history ADD COLUMN signals' in src, 'history 缺自愈迁移'

    def test_sharding_manager_migration(self):
        """status_snapshot 属分库 snapshot_cache.db → 迁移须在 sharding_manager 分库连接执行
        （ECM 总库 DDL 无此表，ALTER 无效——491-5 复核修正）"""
        import app.data.sharding_manager as sm
        src = inspect.getsource(sm)
        assert 'ALTER TABLE {tbl} ADD COLUMN signals' in src, '分库缺 signals 列迁移'
        assert "('status_snapshot', 'status_snapshot_history')" in src
