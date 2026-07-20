"""
历史龙虎榜席位数据补采脚本（278号方案）
=========================================
从 Tushare top_inst API 批量补采历史席位级龙虎榜数据。

用法：
    python backend/scripts/backfill_lhb_detail.py              # 补采最近 30 个交易日
    python backend/scripts/backfill_lhb_detail.py --days 60    # 补采最近 60 个交易日
    python backend/scripts/backfill_lhb_detail.py --start 20260701 --end 20260717  # 指定日期范围
    python backend/scripts/backfill_lhb_detail.py --dry-run    # 仅预览不写入

数据写入 ECM lhb_detail_cache 表，与 akshare_collector 共享存储层。
"""

import sys
import os
from datetime import datetime, timedelta

# 将 backend 目录加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 解析参数
dry_run = False
days_back = 30
start_date_str = None
end_date_str = None

i = 1
while i < len(sys.argv):
    if sys.argv[i] == '--dry-run':
        dry_run = True
    elif sys.argv[i] == '--days' and i + 1 < len(sys.argv):
        days_back = int(sys.argv[i + 1])
        i += 1
    elif sys.argv[i] == '--start' and i + 1 < len(sys.argv):
        start_date_str = sys.argv[i + 1]
        i += 1
    elif sys.argv[i] == '--end' and i + 1 < len(sys.argv):
        end_date_str = sys.argv[i + 1]
        i += 1
    i += 1


def get_trading_dates(days=30):
    """生成最近 N 个交易日（含今日）的日期列表（YYYYMMDD 格式）"""
    dates = []
    today = datetime.now()
    # 往前推 days*2 天确保覆盖足够交易日
    for d in range(days * 2):
        day = (today - timedelta(days=d)).strftime('%Y%m%d')
        if day not in dates:
            dates.append(day)
        if len(dates) >= days:
            break
    return sorted(dates)


def main():
    from app.data import DataManager
    from app.data.enhanced_cache_manager import get_ecm_instance

    dm = DataManager()

    if start_date_str and end_date_str:
        # 生成指定范围内的日期（取所有可能日期，API 会自动跳过非交易日）
        start = datetime.strptime(start_date_str, '%Y%m%d')
        end = datetime.strptime(end_date_str, '%Y%m%d')
        dates = []
        cur = start
        while cur <= end:
            dates.append(cur.strftime('%Y%m%d'))
            cur += timedelta(days=1)
    else:
        dates = get_trading_dates(days_back)

    print(f"{'='*60}")
    print(f"龙虎榜席位数据历史补采")
    print(f"{'='*60}")
    if dry_run:
        print(f"  [DRY RUN] 仅预览，不会写入数据")
    print(f"  日期范围: {dates[0]} ~ {dates[-1]} ({len(dates)} 天)")
    print(f"{'='*60}")
    print()

    # 检查已存在的记录
    ecm = get_ecm_instance()
    existing = ecm._query_df("SELECT DISTINCT trade_date FROM lhb_detail_cache")
    existing_dates = set()
    if not existing.empty:
        existing_dates = set(str(d).replace('-', '') for d in existing['trade_date'].values)
    print(f"  已有数据: {len(existing_dates)} 天")
    print()

    total = 0
    success = 0
    skipped = 0
    failed = 0

    for i, date in enumerate(dates):
        if date in existing_dates:
            skipped += 1
            continue

        if not dry_run:
            try:
                count = dm.sync_lhb_detail_data(trade_date=date)
                if count > 0:
                    total += count
                    success += 1
                    print(f"  [{(i+1):3d}/{len(dates)}] ✅ {date}: {count} 条席位记录")
                else:
                    # 可能是非交易日或无数据
                    skipped += 1
                    print(f"  [{(i+1):3d}/{len(dates)}] ⚠️ {date}: 无数据", end='\r')
            except Exception as e:
                failed += 1
                print(f"  [{(i+1):3d}/{len(dates)}] ❌ {date}: {e}")
        else:
            # 预览模式：只检查是否有数据
            try:
                raw = dm.tushare.get_top_inst(date)
                if raw:
                    print(f"  [{(i+1):3d}/{len(dates)}] 📋 {date}: {len(raw)} 条待写入")
                    total += len(raw)
                else:
                    print(f"  [{(i+1):3d}/{len(dates)}] ⚠️ {date}: 无数据", end='\r')
            except Exception as e:
                print(f"  [{(i+1):3d}/{len(dates)}] ❌ {date}: {e}")

    print()
    print(f"{'='*60}")
    if dry_run:
        print(f"  DRY RUN 完成: 共 {total} 条记录待写入 ({success} 天有数据)")
    else:
        print(f"  补采完成:")
        print(f"    写入席位记录: {total} 条")
        print(f"    成功天数: {success} 天")
        print(f"    跳过(已有/无数据): {skipped} 天")
        print(f"    失败: {failed} 天")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
