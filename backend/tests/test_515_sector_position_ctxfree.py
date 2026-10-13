"""515号 — dim8 板块定位句：无 Flask app context 时行业取数兜底（raw sqlite 读 app.db）。

背景：`DataManager.get_stock_industry` 依赖 Flask-SQLAlchemy（需 app context）；
daemon SIG 预计算路径（`_precompute_strategy_signals`→dim8 归集→`_sector_position_sentence`）
无 context → 抛错被 except 吞 → 全市场「板块定位句」丢失（2026-10-13 实证 5557 条）。
修复（C 双管之 B）：无 context 时兜底 raw sqlite 读 app.db 的 `stocks.industry`（只读、语义等价）。
"""
import sqlite3
import threading

from app.config import Config
from app.data import DataManager


def _make_app_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE stocks (ts_code TEXT, industry TEXT)")
    con.executemany("INSERT INTO stocks VALUES (?, ?)", rows)
    con.commit()
    con.close()


def _run_in_thread(fn):
    """在独立线程执行——新线程无 Flask app context（复现 daemon 无 context 场景）。"""
    out = {}

    def _work():
        out['r'] = fn()

    t = threading.Thread(target=_work)
    t.start()
    t.join()
    return out.get('r')


def test_get_stock_industry_ctxfree_fallback(tmp_path, monkeypatch):
    _make_app_db(tmp_path / 'app.db', [('000001.SZ', '银行'), ('600519.SH', '白酒')])
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(DataManager, '__init__', lambda self: None)  # 免 ECM 构造
    monkeypatch.setattr(DataManager, '_industry_ctxfree_map', None)

    ind = _run_in_thread(lambda: DataManager().get_stock_industry('000001.SZ'))
    assert ind == '银行'  # 无 context → ORM 抛错 → raw sqlite 兜底命中


def test_get_stock_industry_batch_ctxfree_fallback(tmp_path, monkeypatch):
    _make_app_db(tmp_path / 'app.db', [('000001.SZ', '银行'), ('600519.SH', '白酒')])
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(DataManager, '__init__', lambda self: None)
    monkeypatch.setattr(DataManager, '_industry_ctxfree_map', None)

    m = _run_in_thread(
        lambda: DataManager().get_stock_industry_batch(['000001.SZ', '600519.SH', '999999.SZ'])
    )
    assert m.get('000001.SZ') == '银行'
    assert m.get('600519.SH') == '白酒'
    assert m.get('999999.SZ') is None
