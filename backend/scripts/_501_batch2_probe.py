"""501号 批次2 探针——base/registry 加固（#R5/#R6/#R27/#R28/#R30/#R38/#R39）

隔离/桩验证（不发真实查询、不写库）：
  #R5   get_info 返回拷贝（mutate 返回值不污染类属性）；实例 _params/_tags 为每实例副本
  #R6   set_param 类型/范围校验（period=0 抛 ValueError）；__init__ 默认值越界抛错
  #R27  check_data 空表 → False
  #R28  get_factor_registry 并发首调只建一次（多线程双检锁）
  #R30  get_all_factors_info 坏因子 try/except 跳过不中断
  #R38  required_columns 字符串归一为列表
  #R39  search_factors name_cn=None 守卫不抛错
  全量  builtin 全部因子加载 + get_info 实例化不抛错（注册表完整）
"""
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


from app.factors.base import BaseFactor, FactorParam  # noqa: E402
from app.factors.registry import FactorRegistry, get_factor_registry  # noqa: E402


# ══════════════ #R6：参数校验 ══════════════
class _VF(BaseFactor):
    name = "PROBE_PARAM_CHECK"
    params = [FactorParam("period", 20, "int", 1, 252, "周期")]

    def calculate(self, data):
        return data['close']


_f = _VF()
check(_f.get_param("period") == 20, "#R6 默认 period=20 正常")
try:
    _f.set_param("period", 0)
    check(False, "#R6 period=0 应抛 ValueError")
except ValueError:
    check(True, "#R6 period=0 抛 ValueError")
try:
    _f.set_param("period", "abc")
    check(False, "#R6 period='abc' 应抛 ValueError")
except ValueError:
    check(True, "#R6 period='abc' 抛 ValueError")
try:
    _VF(period=999)
    check(False, "#R6 __init__ period=999 越界应抛 ValueError")
except ValueError:
    check(True, "#R6 __init__ period=999 越界抛 ValueError")
check(_f.get_param("period") == 20, "#R6 非法 set_param 后原值不变（先校验后写入）")

# ══════════════ #R38：required_columns 字符串归一 ══════════════
class _RC(BaseFactor):
    name = "PROBE_REQCOLS"
    required_columns = "close"

    def calculate(self, data):
        return data['close']


_rc = _RC()
check(_rc.check_data(pd.DataFrame({'close': [1.0]})),
      "#R38 required_columns='close' 字符串归一 → 有 close 通过")
check(not _rc.check_data(pd.DataFrame({'open': [1.0]})),
      "#R38 缺 close → False（字符串不再按字符迭代）")

# ══════════════ #R27：空表校验 ══════════════
_base = _VF()
check(not _base.check_data(pd.DataFrame()),
      "#R27 空 DataFrame → check_data False")
check(not _base.check_data(None),
      "#R27 None → check_data False")

# ══════════════ #R5：get_info 拷贝 + 实例副本 ══════════════
class _GF(BaseFactor):
    name = "PROBE_GETINFO"
    name_cn = "探针"
    category = "probe"
    tags = {"style": ["a"]}
    related_factors = ["X"]
    params = [FactorParam("n", 5, "int", 1, 20, "n")]
    required_columns = ["close"]

    def calculate(self, data):
        return data['close']


_g1 = _GF()
info = _g1.get_info()
info["tags"]["style"].append("b")
info["relate"].append("Y")
info["required_columns"].append("vol")
check(_g1.get_info()["tags"]["style"] == ["a"],
      f"#R5 mutate get_info 返回 tags 不污染类属性（实际 {_g1.get_info()['tags']['style']}）")
check(_g1.get_info()["relate"] == ["X"],
      f"#R5 mutate relate 不污染（实际 {_g1.get_info()['relate']}）")
check(_g1.get_info()["required_columns"] == ["close"],
      f"#R5 mutate required_columns 不污染（实际 {_g1.get_info()['required_columns']}）")
_g2 = _GF()
check(_g2._params is not _GF.params and _g2._params == _GF.params,
      "#R5 实例 _params 为副本且值一致")
check(_g2._tags is not _GF.tags,
      "#R5 实例 _tags 独立副本")

# ══════════════ #R30：get_all_factors_info 坏因子跳过 ══════════════
class _Bad(BaseFactor):
    name = "PROBE_BAD"
    def __init__(self, **kw):
        raise RuntimeError("构造失败")
    def calculate(self, data):
        return data['close']


_r = FactorRegistry()
_r.register(_VF)
_r.register(_Bad)
_r.register(_GF)
_infos = _r.get_all_factors_info()
names = [i["name"] for i in _infos]
check("PROBE_PARAM_CHECK" in names and "PROBE_GETINFO" in names,
      f"#R30 正常因子信息保留（实际 {names}）")
check("PROBE_BAD" not in names,
      "#R30 坏因子被跳过（不中断整表）")

# ══════════════ #R39：search_factors None 守卫 ══════════════
class _NoneCn(BaseFactor):
    name = "PROBE_NONECN"
    name_cn = None
    description = None
    def calculate(self, data):
        return data['close']


_r2 = FactorRegistry()
_r2.register(_NoneCn)
_res = _r2.search_factors("PROBE_NONECN")
check(_res == ["PROBE_NONECN"],
      f"#R39 name_cn/description=None 搜索不抛错（实际 {_res}）")

# ══════════════ #R28：并发双检锁 ══════════════
# 重置全局注册表后多线程并发首调，只应构建一次
import app.factors.registry as _regmod  # noqa: E402

_saved_builtin = _regmod._load_builtin_factors  # 备份真函数
_regmod._global_registry = None
_regmod._load_builtin_factors = lambda reg: reg  # 桩：不真加载（只验并发建表单次）
seen = []


def _call():
    reg = _regmod.get_factor_registry()
    seen.append(id(reg))


threads = [threading.Thread(target=_call) for _ in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check(len(set(seen)) == 1,
      f"#R28 并发首调 8 线程只建 1 个注册表（实际 {len(set(seen))} 个）")
# 恢复真实加载，验证全量因子可加载 + get_info 实例化不抛错
_regmod._global_registry = None
_regmod._load_builtin_factors = _saved_builtin  # 恢复真函数
full = get_factor_registry()
all_names = full.list_factors()
_all_ok = True
for nm in all_names:
    try:
        inst = full.get_factor(nm)
        inst.get_info()
    except Exception as e:
        _all_ok = False
        print(f"    !! {nm} get_info 失败: {e}")
check(len(all_names) >= 50, f"#R28 全量因子注册 {len(all_names)} 个")
check(_all_ok, "#R28 全量因子 get_info 实例化不抛错")

# ══════════════ 汇总 ══════════════
print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print("ALL PASSED")
