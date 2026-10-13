"""515 号定向验证探针（只读，不入库、不改管道）。

复刻 daemon SIG 预计算中 dim8 归集的「旧失败条件」——即在**无 Flask app context**下调用
dim8 归集（daemon 里 `_load_tags`/`_build_dim_engine_results` 本就无 context，仅 dim8 归集
被 515 包了 context）。据此确认 515 修复（B 兜底 + 句恢复）在旧失败条件下生效：

  0) 无 context 时 ORM（`db.session.query(Stock)`）必抛 `RuntimeError` —— 证明旧失败条件存在；
  1) 无 context 直调 `DataManager.get_stock_industry` —— B 兜底返回真实行业（不再抛）；
  2) 无 context 直调 dim8 板块定位句 —— 产句（构造真实行业 + sector_heat）；
  3) 无 context 复刻 daemon 真实链路（StatusEngine → `build_seven_dim_from_dim_results`）抽样；
  汇总：无 context 下捕获「dim8 板块定位句构建失败」warning 数（修复后应 = 0）。

用法：`cd backend && PYTHONPATH=. .venv/bin/python scripts/_515_ctxfree_verify_probe.py`
"""
import logging
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND)
sys.path.insert(0, _BACKEND)
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ.setdefault("DATA_DIR", os.path.join(_PROJECT_ROOT, "data"))

_hits = []


class _WarnCap(logging.Handler):
    def emit(self, rec):
        try:
            msg = rec.getMessage()
        except Exception:
            msg = str(getattr(rec, "msg", ""))
        if "板块定位句构建失败" in msg:
            _hits.append(msg)


logging.getLogger().addHandler(_WarnCap())
logging.getLogger().setLevel(logging.WARNING)

from app import db  # noqa: E402
from app.data import DataManager  # noqa: E402
from app.models import Stock  # noqa: E402
from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    _sector_position_sentence,  # noqa: E402
)

CODES = ["600519.SH", "000001.SZ", "300750.SZ", "000002.SZ", "601318.SH", "600036.SH"]


def _part0():
    print("== 0) 证明『旧失败条件』存在：无 app context 时 ORM 必抛 ==")
    try:
        db.session.query(Stock).first()
        print("   ORM 未抛错（?? 说明当前意外处于 context 中）")
    except RuntimeError as e:
        print(f"   ORM 抛 RuntimeError（旧失败条件成立）: {str(e).splitlines()[0]}")
    except Exception as e:
        print(f"   ORM 抛 {type(e).__name__}: {e}")


def _part1(dm):
    print("\n== 1) 无 app context 直调 get_stock_industry（B 兜底核心）==")
    for c in CODES:
        try:
            print(f"   {c} -> {dm.get_stock_industry(c)!r}")
        except Exception as e:
            print(f"   {c} -> RAISED {type(e).__name__}: {e}")


def _part2(dm):
    print("\n== 2) 无 app context 直调 dim8 板块定位句（构造真实行业 + sector_heat）==")
    for c in CODES:
        ind = dm.get_stock_industry(c)
        dim_results = {"signal": {"data_context": {"sector_heat": {
            ind: {"heat_level": "top_20", "rank": 15},
        }}}}
        print(f"   {c} (行业={ind}) -> {_sector_position_sentence(dim_results, c)!r}")


def _part3(dm):
    print("\n== 3) 无 app context 复刻 daemon dim8 归集（真实链路，抽样）==")
    try:
        from app.opportunity_atlas.status_engine import (
            StatusEngine,
            build_seven_dim_from_dim_results,
        )
        se = StatusEngine()
        for c in CODES[:4]:
            try:
                tags = se._load_tags(c) or {}
                signals = se._load_signals(c) or {}
                lifecycle = se._signal_lifecycle(c, tags, signals)
                dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=c)
                sh = ((dim_results or {}).get("signal") or {}).get("data_context", {}).get("sector_heat") or {}
                ind = dm.get_stock_industry(c)
                blob = str(build_seven_dim_from_dim_results(dim_results, tags=tags, ts_code=c))
                direct = _sector_position_sentence(dim_results, c)
                print(f"   {c}: sector_heat_n={len(sh)} 含本行业={ind in sh} | "
                      f"seven_dim含'板块定位：'={'板块定位：' in blob} | 直调句={direct!r}")
            except Exception as e:
                import traceback
                print(f"   {c}: FATAL {type(e).__name__}: {e}")
                traceback.print_exc()
    except Exception as e:
        import traceback
        print(f"   StatusEngine 初始化失败: {type(e).__name__}: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    dm = DataManager()
    _part0()
    _part1(dm)
    _part2(dm)
    _part3(dm)
    print(f"\n== 汇总：无 context 下捕获『板块定位句构建失败』warning 数 = {len(_hits)} ==")
    for m in _hits[:8]:
        print("   ", m)
