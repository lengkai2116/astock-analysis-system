"""440号 样本级回归验证（只读：evaluate 重算，不落库）

验证 440 修复后 dims 残留删除/引擎自产/中文化在真实数据上的效果。
重点核查三个曾被空 dims 劫持的维度：
  - structure  : judgment['structure'] 不再恒"盘整"
  - volume_price: judgment['state'] 不再恒"中性"
  - emotion     : status_description['stock'] 不再恒"中性"；bociasi/quadrant 已中文

用法：.venv/bin/python scripts/_440_sample_regression.py [N]   # N=样本数(默认1)
"""
import os
import sys
import json
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    # 抽样：覆盖沪/深/创不同代码段
    prefix_codes = ['000001.SZ', '000002.SZ', '000063.SZ', '000333.SZ', '000651.SZ',
                    '000858.SZ', '000938.SZ', '002415.SZ', '002475.SZ', '002594.SZ',
                    '300059.SZ', '300122.SZ', '300124.SZ', '300136.SZ', '300142.SZ',
                    '300308.SZ', '300433.SZ', '300750.SZ', '300760.SZ', '600000.SH',
                    '600009.SH', '600030.SH', '600036.SH', '600050.SH', '600104.SH',
                    '600276.SH', '600519.SH', '600585.SH', '600887.SH', '601318.SH']
    codes = prefix_codes[:n]
    engine = StatusEngine()

    struct_cnt = Counter()
    vp_cnt = Counter()
    stock_cnt = Counter()
    ma_en_sample = []
    chip_en_sample = []
    bociasi_en_sample = []
    errors = []

    for code in codes:
        try:
            r = engine.evaluate(code)
            if not r:
                errors.append(f'{code}: evaluate 返回空')
                continue
            dr = json.loads(r.get('dim_engine_results', '{}') or '{}')
        except Exception as e:
            errors.append(f'{code}: {type(e).__name__}: {e}')
            continue

        # structure
        s = dr.get('structure') or {}
        struct_cnt[str(s.get('judgment', {}).get('structure', '?')[:4])] += 1
        # volume_price / vp_state
        vp = dr.get('volume_price') or {}
        vp_cnt[str(vp.get('judgment', {}).get('state', '?')[:4])] += 1
        # emotion stock
        em = dr.get('emotion') or {}
        sd_em = em.get('status_description') or {}
        stock_cnt[str(sd_em.get('stock', '?')[:12])] += 1
        # 中英映射残留采样
        s_sd = s.get('status_description') or {}
        vp_sd = vp.get('status_description') or {}
        for key in ('vs_ma',):
            v = str(s_sd.get(key, ''))
            if any(x in v for x in ('mixed', 'bullish', 'bearish', 'concentrating', 'dispersing', 'stable')):
                ma_en_sample.append(f'{code}:{key}={v}')
        for key in ('plain',):
            v = str(vp_sd.get(key, ''))
            if 'mixed' in v or 'bearish' in v or 'bullish' in v:
                ma_en_sample.append(f'{code}:{key}={v}')
        for key in ('bociasi_quick', 'bociasi_slow', 'quadrant'):
            v = str(sd_em.get(key, ''))
            if any(x in v for x in ('NEUTRAL', 'BUY', 'BEARISH', 'WATCH', 'BULLISH', 'MM —')) or 'MM' in v:
                bociasi_en_sample.append(f'{code}:{key}={v}')
        chip = str(sd_em.get('plain', '')) + str(s_v := s_sd.get('vs_chip', ''))
        if any(x in chip for x in ('筹码concentrating', '筹码dispersing', '筹码stable')):
            chip_en_sample.append(f'{code}:chip={chip}')

    print(f'\n{"="*64}\n440 样本级回归（{len(codes)} 只, 耗时 {time.time()-time.time():.0f}s 内）\n{"="*64}')
    print('\n[structure] judgment.structure 分布:')
    for k, v in struct_cnt.most_common(): print(f'   {k}: {v}')
    print('\n[volume_price] judgment.state 分布:')
    for k, v in vp_cnt.most_common(): print(f'   {k}: {v}')
    print('\n[emotion] status_description.stock 分布:')
    for k, v in stock_cnt.most_common(): print(f'   {k}: {v}')
    print('\n[EN残留] 含英文枚举的样本（应尽量少/无）:')
    for x in ma_en_sample[:10]: print(f'   {x}')
    if not ma_en_sample: print('   无')
    print('\n[chip EN残留] 筹码英文（应无）:')
    for x in chip_en_sample[:10]: print(f'   {x}')
    if not chip_en_sample: print('   无')
    print('\n[bociasi/quadrant] 英文兜底采样（应无 NEUTRAL/MM-兜底）:')
    for x in bociasi_en_sample[:10]: print(f'   {x}')
    if not bociasi_en_sample: print('   无')
    if errors:
        print(f'\n[错误] {len(errors)} 条:')
        for e in errors[:10]: print(f'   {e}')


if __name__ == '__main__':
    t0 = time.time()
    main()
    print(f'\n总耗时: {time.time()-t0:.2f}s')
