"""468号 8股全链路回归探针（dim1→dim4→dim8 真实数据，只读不写）

核查 ①-⑤ 补产出的实际输出：
  ① phase 投票明细（fund_flow 文本的「投票:fund=..」）
  ② fund_flow 5日大单净额（净流入/净流出 X.X亿）
  ③ crowding 文本含 融资占比/换手/波动 + 有效信号数
  ④ _assess_signal 从 active_signal 增强 detail（price/confidence/reason）
  ⑤ audit「筹码集中」收紧为 concentrating（stable 不再满足）
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine

CODES = ['600036.SH', '000002.SZ', '600519.SH', '300750.SZ',
         '002594.SZ', '688981.SH', '000001.SZ', '601318.SH']


def probe(ts_code):
    engine = StatusEngine()
    r = engine.evaluate(ts_code)
    dr = json.loads(r.get('dim_engine_results', '{}'))
    d4 = dr.get('chip_fund') or {}
    sd = d4.get('status_description', {}) or {}
    audit = d4.get('audit', {}) or {}

    print(f'\n===== {ts_code} =====')
    # ① phase 投票
    ph = sd.get('phase', '')
    print(f'  phase : {ph}')
    print(f'    [①投票明细] {"有" if "投票:" in ph else "无"}')
    # ② fund_flow 净额
    ff = sd.get('fund_flow', '')
    print(f'  flow  : {ff}')
    print(f'    [②5日净额] {"有" if any(k in ff for k in ["净流入", "净流出"]) else "无"}')
    # ③ crowding 三信号
    cw = sd.get('crowding', '')
    print(f'  crowd : {cw}')
    print(f'    [③融资占比] {"有" if "融资占比" in cw else "无"}  '
          f'[换手] {"有" if "换手" in cw else "无"}  '
          f'[波动] {"有" if "波动" in cw else "无"}  '
          f'[信号数] {"有" if "信号可用" in cw else "无"}')
    # ⑤ audit 筹码集中
    for cond in audit.get('conditions', []):
        if cond.get('name') == '筹码集中':
            print(f'  [⑤筹码集中] satisfied={cond.get("satisfied")} '
                  f'actual={cond.get("actual")} threshold={cond.get("threshold")}')
    # ④ signal 增强——真实输出在 status_description['signal']（evaluate 内 _assess_signal(tags)）
    sg = sd.get('signal', '')
    print(f'  [signal] {sg}')
    print(f'    [④增强detail] {"有" if any(k in sg for k in ["信号@", "置信"]) else "无(回退,无活跃信号)"}')


if __name__ == '__main__':
    for c in CODES:
        try:
            probe(c)
        except Exception as e:
            import traceback
            print(f'\n===== {c} =====')
            print(f'  [FATAL] {e}')
            traceback.print_exc()
