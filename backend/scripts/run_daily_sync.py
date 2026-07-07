"""日终同步触发脚本"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]
os.environ['FLASK_APP'] = 'app'

from app import create_app
from app.data.enhanced_cache_manager import EnhancedCacheManager
import pandas as pd
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('sync')

app = create_app()
with app.app_context():
    from app.scheduler_manager import scheduler_manager
    logger.info("开始日终同步...")
    t0 = time.time()
    result = scheduler_manager.run_daily_sync()
    elapsed = time.time() - t0
    logger.info(f"同步完成 | 耗时 {elapsed:.0f}s | 状态: {result.get('status')}")
    for dt in result.get('data_types', []):
        logger.info(f"  {dt['type']}: {dt['count']}条")

    # 验证今日数据
    ecm = EnhancedCacheManager()
    today = time.strftime('%Y-%m-%d')
    for tbl in ['daily_cache', 'daily_basic_cache', 'moneyflow_cache',
                'stk_limit_cache', 'lhb_cache']:
        try:
            cnt = ecm.conn.execute(f"SELECT COUNT(*) FROM \"{tbl}\" WHERE trade_date = ?", [today]).fetchone()[0]
            logger.info(f"  {tbl} 今日({today}): {cnt}行")
        except:
            pass
