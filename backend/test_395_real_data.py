"""395号方案 真实数据测试
策略：从strategy_signal_detail读取daemon已计算的dim_results_json，
     用新dim8代码处理，验证输出。
"""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.data.enhanced_cache_manager import get_ecm_instance
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine


def get_real_stocks():
    """从数据库读取有dim_results的真实股票"""
    ecm = get_ecm_instance()
    rows = ecm.conn.execute(
        "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
        "WHERE dim_results_json IS NOT NULL AND trade_date = ("
        "  SELECT MAX(trade_date) FROM strategy_signal_detail"
        ") LIMIT 5"
    ).fetchall()
    return [(r[0], json.loads(r[1]) if r[1] else {}) for r in rows]


def run_test():
    stocks = get_real_stocks()
    if not stocks:
        print("数据库中无dim_results数据")
        return

    print(f"读取到 {len(stocks)} 只真实股票")
    dim8 = Dim8SummaryEngine()

    for ts_code, dim_results in stocks:
        print(f"\n{'='*80}")
        print(f"股票: {ts_code}")
        print(f"{'='*80}")

        # 检查dim_results结构
        if not isinstance(dim_results, dict):
            print(f"  dim_results类型异常: {type(dim_results)}")
            continue

        available_dims = [k for k in dim_results.keys() if k != 'summary']
        print(f"  可用维度: {available_dims}")

        # 检查valuation是否存在（之前测试中valuation为None）
        for dk in ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']:
            dd = dim_results.get(dk)
            if dd is None:
                print(f"  {dk}: None（引擎未输出）")
            elif isinstance(dd, dict):
                sd = dd.get('status_description')
                jg = dd.get('judgment')
                if sd:
                    light = jg.get('overall_light', '?') if jg else '?'
                    plain = sd.get('plain', '')[:80]
                    print(f"  {dk}: light={light}, plain={plain}")
                else:
                    print(f"  {dk}: 无status_description, keys={list(dd.keys())}")
            else:
                print(f"  {dk}: 类型异常 {type(dd)}")

        # 运行新dim8
        print(f"\n--- 运行新dim8 ---")
        try:
            result = dim8.evaluate(
                dims={}, tags={},
                lifecycle={'dim_results': dim_results, 'ts_code': ts_code}
            )
        except Exception as e:
            print(f"  dim8异常: {e}")
            import traceback
            traceback.print_exc()
            continue

        sd = result.get('status_description', {})
        six_dim = sd.get('six_dim_report', {})

        if six_dim:
            print(f"  six_dim_report: 有 {len(six_dim)} 个维度")
            for dk in ['risk', 'valuation', 'emotion', 'structure', 'volume_price', 'chip_fund']:
                d = six_dim.get(dk, {})
                if d:
                    print(f"\n  【{d.get('title', dk)}】灯色={d.get('light')}")
                    print(f"  判断: {d.get('judgment', '')}")
                    text = d.get('text', '')
                    print(f"  描述: {text[:200]}")
                    ev = d.get('evidence', [])
                    if ev:
                        print(f"  证据: {ev[:2]}")
            print(f"\n  质量: {sd.get('quality_text', '')}")
            print(f"  汇总: {sd.get('plain', '')[:300]}")
        else:
            print(f"  six_dim_report为空")
            print(f"  status_description keys: {list(sd.keys())}")
            # 检查是否命中异常处理
            if 'status_bar' in sd:
                print(f"  → 命中了异常处理（旧格式），说明evaluate()内部出错")


if __name__ == '__main__':
    run_test()
