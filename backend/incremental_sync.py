"""
增量同步脚本 — 按日期同步全市场日线数据
跳过已有的条目，仅插入新数据
"""
import sys
import time
from datetime import datetime, timedelta

# 运行在 app 上下文中
from app import create_app, db
from app.data.tushare_provider import TushareProvider
from app.models import DailyData

app = create_app()

def get_trading_dates_since(last_date_str):
    """生成从 last_date 次日到今天的所有可能的交易日"""
    last = datetime.strptime(last_date_str, '%Y-%m-%d').date()
    today = datetime.now().date()
    
    dates = []
    d = last + timedelta(days=1)
    while d <= today:
        # 跳过周末（周一到周五是交易日，A股没有周末交易）
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    return dates

def sync_date(provider, trade_date, data_manager):
    """同步指定日期的全市场数据"""
    date_str = trade_date.strftime('%Y%m%d')
    
    # 使用Tushare按日期获取全市场数据
    data = provider.get_daily_by_date(date_str)
    if not data:
        print(f'  ⚠️  {date_str}: Tushare 返回空数据')
        return 0
    
    # 过滤掉已在 PostgreSQL 中的条目
    new_count = 0
    for item in data:
        ts_code = item.get('ts_code')
        if not ts_code:
            continue
        existing = DailyData.query.filter_by(
            ts_code=ts_code,
            trade_date=trade_date
        ).first()
        if not existing:
            dd = DailyData(
                ts_code=ts_code,
                trade_date=trade_date,
                open=item.get('open'),
                high=item.get('high'),
                low=item.get('low'),
                close=item.get('close'),
                vol=item.get('vol'),
                amount=item.get('amount'),
                pct_chg=item.get('pct_chg')
            )
            db.session.add(dd)
            new_count += 1
    
    db.session.commit()
    return new_count

with app.app_context():
    print('=' * 60)
    print('🚀 增量数据同步开始')
    print('=' * 60)
    
    provider = TushareProvider()
    dm = __import__('app.data', fromlist=['DataManager']).DataManager()
    
    # 查询 PostgreSQL 中最新的数据日期
    from sqlalchemy import func
    max_date = db.session.query(func.max(DailyData.trade_date)).scalar()
    print(f'📅 当前数据库最新日期: {max_date}')
    
    if not max_date:
        print('❌ 数据库中没有数据')
        sys.exit(1)
    
    # 生成待同步的日期列表
    dates_to_sync = get_trading_dates_since(str(max_date))
    
    if not dates_to_sync:
        print('✅ 数据已是最新，无需同步')
        sys.exit(0)
    
    print(f'📊 待同步交易日: {len(dates_to_sync)} 天')
    for d in dates_to_sync:
        print(f'   {d.strftime("%Y-%m-%d")} ({"周" + "一二三四五六日"[d.weekday()]})')
    
    print()
    total_new = 0
    for trade_date in dates_to_sync:
        date_str = trade_date.strftime('%Y%m%d')
        weekday = "周" + "一二三四五六日"[trade_date.weekday()]
        print(f'📥 同步 {date_str} ({weekday})...', end=' ', flush=True)
        
        try:
            count = sync_date(provider, trade_date, dm)
            total_new += count
            print(f'✅ 新增 {count} 条')
        except Exception as e:
            print(f'❌ 失败: {e}')
            import traceback
            traceback.print_exc()
        
        # Tushare 限流：每秒最多 3-5 次请求
        time.sleep(1)
    
    print()
    print('=' * 60)
    print(f'✅ 同步完成')
    print(f'📊 累计新增数据: {total_new} 条')
    print(f'📅 覆盖 {len(dates_to_sync)} 个交易日')
    print('=' * 60)
