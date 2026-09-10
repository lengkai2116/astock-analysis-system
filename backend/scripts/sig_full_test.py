"""SIG 层 dim1-dim8 全量真实数据测试脚本（只读，不修改代码/方案）

逐维运行 dim1-dim8，核查各维输出是否符合功能定位。
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine


def check_dim(ts_code, dim_name, result, expected_keys):
    """核查单个维度输出"""
    issues = []
    if result is None:
        return {'status': 'FAIL', 'issues': ['维度返回 None（引擎调用失败）']}
    if not isinstance(result, dict):
        return {'status': 'FAIL', 'issues': [f'返回非 dict: {type(result)}']}
    # 检查三轨结构
    for key in ['status_description', 'judgment', 'audit']:
        if key not in result:
            issues.append(f'缺 {key} 键')
    # 检查 expected_keys 是否在 status_description / judgment / 顶层 中
    sd = result.get('status_description', {})
    jg = result.get('judgment', {})
    for k in expected_keys:
        if k not in sd and k not in jg and k not in result:
            issues.append(f'缺字段 {k}')
    status = 'OK' if not issues else 'WARN' if len(issues) <= 2 else 'FAIL'
    return {'status': status, 'issues': issues}


def main():
    codes = ['000001.SZ', '600000.SH', '000002.SZ', '600519.SH', '300750.SZ']
    engine = StatusEngine()

    # 各维功能定位与关键字段
    dim_checks = {
        'signal': ['data_context', 'status_quality', 'overall_light', 'overall_direction'],
        'structure': ['chanlun_direction', 'buy_sell_points', 'overall_light'],
        'volume_price': ['pattern', 'health_score', 'overall_light'],
        'chip_fund': ['phase', 'retail_institution', 'overall_light'],
        'emotion': ['quadrant', 'temperature', 'overall_light'],
        'risk': ['rr_value', 'support_price', 'resistance_price', 'overall_light'],
        'valuation': ['valuation_level', 'pe_percentile', 'overall_light'],
        'summary': ['status_bar', 'consensus_rate', 'conflicts', 'text'],
    }

    all_results = {}
    for code in codes:
        print(f'\n{"="*60}\n股票: {code}\n{"="*60}')
        t0 = time.time()
        try:
            r = engine.evaluate(code)
        except Exception as e:
            print(f'  [FATAL] evaluate 异常: {e}')
            import traceback; traceback.print_exc()
            continue
        elapsed = time.time() - t0
        print(f'  evaluate 耗时: {elapsed:.2f}s')

        if not r:
            print('  [FATAL] evaluate 返回空')
            continue

        # 解析 dim_engine_results
        dr = {}
        try:
            dr = json.loads(r.get('dim_engine_results', '{}'))
        except Exception as e:
            print(f'  [WARN] dim_engine_results 解析失败: {e}')

        print(f'  dim_engine_results 键: {list(dr.keys())}')
        all_results[code] = {'elapsed': elapsed, 'dims': {}}

        for dim, expected in dim_checks.items():
            result = dr.get(dim)
            check = check_dim(code, dim, result, expected)
            all_results[code]['dims'][dim] = check
            # 打印关键信息
            if result and isinstance(result, dict):
                jg = result.get('judgment', {})
                sd = result.get('status_description', {})
                light = jg.get('overall_light', jg.get('light', '?'))
                direction = jg.get('overall_direction', '?')
                plain = sd.get('plain', '')[:80]
                print(f'  [{dim}] {check["status"]} light={light} dir={direction}')
                if plain:
                    print(f'         plain: {plain}')
                if check['issues']:
                    print(f'         issues: {check["issues"]}')
            else:
                print(f'  [{dim}] {check["status"]} (无输出)')

    # 汇总
    print(f'\n{"="*60}\n汇总\n{"="*60}')
    total_ok = 0
    total_warn = 0
    total_fail = 0
    for code, data in all_results.items():
        for dim, check in data['dims'].items():
            if check['status'] == 'OK':
                total_ok += 1
            elif check['status'] == 'WARN':
                total_warn += 1
            else:
                total_fail += 1
    print(f'OK: {total_ok}, WARN: {total_warn}, FAIL: {total_fail}')
    print(f'耗时: {[round(d["elapsed"],2) for d in all_results.values()]}')


if __name__ == '__main__':
    main()
