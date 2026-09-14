"""431号 G2：配置加载单测（430号 G2 / 431 §六 第 8 项）

覆盖 430 号问题 #12「配置加载零测试」，并作为 431 F1 合并加载器的回归网：
  - config/__init__.py（F1 后唯一实现）：_CONFIG_DIR / load_yaml（lru_cache）/
    get_status_engine_config / get_signal_registry / load_strategy_config /
    get_strategy_config（热重载）
  - app/services/status_config.py：薄再导出壳（实现唯一在 config 包）
  - 唯一权威位置 backend/config/（430号 §9 第 3 条；项目根副本已 git rm）
  - arbiter 阈值与冲突规则确由 YAML 驱动（非代码常量），失败时告警且不静默（F3 回归网）

纯配置读取，不触库、不写盘，因此无需 DATA_DIR 沙盒。
"""
import logging
import os

import pytest


def _status_config():
    from app.services import status_config
    return status_config


# ── 1. 权威位置（430号 §9 第 3 条） ──

def test_config_dir_points_to_backend_config():
    sc = _status_config()
    assert os.path.basename(sc._CONFIG_DIR) == 'config'
    assert os.path.basename(os.path.dirname(sc._CONFIG_DIR)) == 'backend'
    assert os.path.isdir(sc._CONFIG_DIR)


@pytest.mark.parametrize('name', [
    'status_engine.yaml', 'signal_registry.yaml', 'strategy_defaults.yaml',
])
def test_authoritative_yamls_exist_in_backend_config(name):
    sc = _status_config()
    assert os.path.exists(os.path.join(sc._CONFIG_DIR, name))


@pytest.mark.parametrize('name', ['status_engine.yaml', 'signal_registry.yaml'])
def test_project_root_config_copy_absent(name):
    """430号 §9 第 3 条：唯一权威位置在 backend/config/，项目根副本已 git rm"""
    sc = _status_config()
    project_root = os.path.dirname(os.path.dirname(sc._CONFIG_DIR))
    assert not os.path.exists(os.path.join(project_root, 'config', name))


# ── 2. load_yaml 基础语义（缺失/缓存/空文件） ──

def test_load_yaml_missing_file_returns_empty_dict():
    assert _status_config().load_yaml('__no_such_431__.yaml') == {}


def test_load_yaml_is_lru_cached():
    sc = _status_config()
    sc.load_yaml.cache_clear()
    first = sc.load_yaml('status_engine.yaml')
    assert sc.load_yaml('status_engine.yaml') is first
    assert sc.load_yaml.cache_info().hits >= 1
    sc.load_yaml.cache_clear()
    assert sc.load_yaml('status_engine.yaml') == first


def test_load_yaml_empty_file_returns_empty_dict(tmp_path, monkeypatch):
    """F1 合并后 _CONFIG_DIR 权威在 config 包；猴补须打在权威模块上"""
    import config as cfg_mod

    (tmp_path / 'empty_431.yaml').write_text('', encoding='utf-8')
    monkeypatch.setattr(cfg_mod, '_CONFIG_DIR', str(tmp_path))
    cfg_mod.load_yaml.cache_clear()
    try:
        assert cfg_mod.load_yaml('empty_431.yaml') == {}
    finally:
        cfg_mod.load_yaml.cache_clear()


# ── 3. status_engine.yaml / signal_registry.yaml 内容契约 ──

def test_status_engine_config_content():
    cfg = _status_config().get_status_engine_config()
    assert cfg['version'] == 2
    assert cfg['jud_engine_version'] == 'v390'
    assert cfg['consensus'] == {'enter_threshold': 0.67, 'bearish_strong': 0.67}
    assert cfg['conflict_rules']['enabled'] is True
    assert set(cfg['conflict_rules']['rules']) == {
        'trend_vs_multi', 'high_profit_no_flow', 'distributing_vs_confirm',
        'risk_high_vs_confirm', 'high_profit_no_presence', 'deep_valuation_confirm',
    }
    l0 = cfg['l0']
    assert l0['hard_risks'] == ['regulatory']
    assert l0['soft_risk_coeff']['deep_position_cap'] == 0.3
    assert l0['emotion_position_cap'] == {
        'ice': 0.10, 'ebb': 0.30, 'normal': 0.60, 'recovery': 0.60, 'positive': 0.80,
    }
    assert l0['hold_only_stages'] == ['已延伸']


def test_status_engine_removed_keys_do_not_come_back():
    """430号 §9 第 5 条已移除的死键/整块不得回归"""
    cfg = _status_config().get_status_engine_config()
    assert 'dimension_weights' not in cfg
    for dead in ('color_high', 'color_low', 'neutral_is_zero'):
        assert dead not in cfg['consensus']


def test_signal_registry_content():
    reg = _status_config().get_signal_registry()
    assert reg['version'] == 1
    assert set(reg['signals']) == {
        'chan_third_buy', 'volume_breakout', 'ma_bullish',
        'platform_breakout', 'pattern_up',
    }
    for key, sig in reg['signals'].items():
        assert set(sig) >= {'name', 'trigger', 'verify_days', 'verify_rule', 'lifecycle'}, key
        assert isinstance(sig['verify_days'], int) and sig['verify_days'] > 0, key
        lifecycle = sig['lifecycle']
        assert set(lifecycle) == {'initial', 'extended'}, key
        assert lifecycle['initial']['dist_pct'] < lifecycle['extended']['dist_pct'], key


# ── 4. 策略配置加载器（config/__init__.py） ──

def test_strategy_loader_resolves_same_config_dir():
    """F1 锚点：唯一实现解析到的配置目录就是它自身所在的 backend/config/"""
    import config as cfg_mod

    sc = _status_config()
    assert os.path.abspath(os.path.dirname(cfg_mod.__file__)) == os.path.abspath(sc._CONFIG_DIR)

    by_default = cfg_mod.load_strategy_config()
    by_explicit = cfg_mod.load_strategy_config(
        os.path.join(sc._CONFIG_DIR, 'strategy_defaults.yaml')
    )
    assert by_default == by_explicit
    assert by_default['chip_distribution']['lookback_period'] == 120
    assert by_default['chanlun']['min_kline'] == 5


def test_get_strategy_config_caches_and_hot_reloads():
    """F1 合并后策略配置与其余 yaml 共用同一个 lru_cache"""
    import config as cfg_mod

    cfg_mod.load_yaml.cache_clear()
    first = cfg_mod.get_strategy_config()
    assert cfg_mod.get_strategy_config() is first
    assert cfg_mod.get_strategy_config(reload=True) is not first
    assert cfg_mod.get_strategy_config() == first
    cfg_mod.load_yaml.cache_clear()


def test_status_config_is_thin_shim():
    """F1：两套加载器已合并——status_config 退化为薄再导出壳，实现唯一在 config 包"""
    import config as cfg_mod

    sc = _status_config()
    assert sc.load_yaml is cfg_mod.load_yaml
    assert sc.get_status_engine_config is cfg_mod.get_status_engine_config
    assert sc.get_signal_registry is cfg_mod.get_signal_registry
    assert os.path.abspath(sc._CONFIG_DIR) == os.path.abspath(cfg_mod._CONFIG_DIR)


def test_strategy_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    """F1 口径：缺失文件一律返回 {}，不再抛 FileNotFoundError"""
    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, '_CONFIG_DIR', str(tmp_path))
    cfg_mod.load_yaml.cache_clear()
    try:
        assert cfg_mod.get_strategy_config() == {}
        assert cfg_mod.load_strategy_config(str(tmp_path / '__no_such__.yaml')) == {}
    finally:
        cfg_mod.load_yaml.cache_clear()


# ── 5. 消费侧接线：arbiter 阈值/规则确由 YAML 驱动 ──

def test_arbiter_thresholds_are_yaml_driven(monkeypatch):
    from app.opportunity_atlas import arbiter
    from app.services import status_config

    def fake():
        return {'consensus': {'bearish_strong': 0.5, 'enter_threshold': 0.8}}

    monkeypatch.setattr(status_config, 'get_status_engine_config', fake)
    arbiter._load_thresholds()
    assert (arbiter._BEARISH_STRONG, arbiter._BULLISH_ENTER) == (0.5, 0.8)

    monkeypatch.undo()
    arbiter._load_thresholds()
    assert (arbiter._BEARISH_STRONG, arbiter._BULLISH_ENTER) == (0.67, 0.67)


def test_arbiter_conflict_rules_yaml_semantics(monkeypatch):
    from app.opportunity_atlas import arbiter
    from app.services import status_config

    queue = []

    def fake():
        return queue.pop(0)

    monkeypatch.setattr(status_config, 'get_status_engine_config', fake)
    defaults = arbiter._DEFAULT_CONFLICT_RULES
    assert len(defaults) == 6

    queue.append({'conflict_rules': {'enabled': False}})
    assert arbiter._load_conflict_rules() == set()

    queue.append({'conflict_rules': {'enabled': True, 'rules': ['trend_vs_multi']}})
    assert arbiter._load_conflict_rules() == {'trend_vs_multi'}

    queue.append({'conflict_rules': {'enabled': True}})
    assert arbiter._load_conflict_rules() == set(defaults)

    queue.append({})
    assert arbiter._load_conflict_rules() == set(defaults)

    monkeypatch.undo()
    assert arbiter._load_conflict_rules() == set(defaults)


def test_load_failure_warns_but_keeps_previous_values(monkeypatch, caplog):
    """F3 回归网：读取失败必须显式告警，且沿用当前值而非静默吞掉"""
    from app.opportunity_atlas import arbiter
    from app.services import status_config

    def boom():
        raise RuntimeError('431 G2 注入故障')

    monkeypatch.setattr(status_config, 'get_status_engine_config', boom)
    with caplog.at_level(logging.WARNING, logger='app.opportunity_atlas.arbiter'):
        arbiter._load_thresholds()
        rules = arbiter._load_conflict_rules()

    assert (arbiter._BEARISH_STRONG, arbiter._BULLISH_ENTER) == (0.67, 0.67)
    assert rules == set(arbiter._DEFAULT_CONFLICT_RULES)
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any('共识阈值读取失败' in m for m in messages), messages
    assert any('冲突规则配置读取失败' in m for m in messages), messages
