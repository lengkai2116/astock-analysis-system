"""442号缺陷④ 临时实证：app_context 下 compute_all_heat 产出真实 heat"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app import create_app
from app.engine.framework.sector_rotation_model import SectorRotationModel
from app.data import DataManager

app = create_app()
dm = DataManager()
with app.app_context():
    # 全市场活跃票（daily 最新日）抽样 40（足够覆盖 3+ 行业成员）
    from app.data.sharding_manager import sharding_manager as sm
    dc = sm.get_connection(sm.get_db_for_table('daily_cache'))
    latest = dc.execute('SELECT MAX(trade_date) FROM daily_cache').fetchone()[0]
    codes = [r[0] for r in dc.execute(
        "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=? LIMIT 40", [latest]).fetchall()]
    all_data = {}
    for c in codes:
        df = dm.get_cached_daily_data(c)
        if df is not None and not df.empty:
            all_data[c] = df
    print(f'RESULT 加载 {len(all_data)}/{len(codes)} 只日线', flush=True)
    sr = SectorRotationModel()
    sh = sr.compute_all_heat(all_data)
    print(f'RESULT all_heat 行业数: {len(sh)}', flush=True)
    for ind, info in list(sh.items())[:6]:
        print(f'RESULT   {ind}: {info}', flush=True)
    # 000002/600519 的 evaluate
    for c in ['000002.SZ', '600519.SH']:
        ev = sr.evaluate(c)
        print(f'RESULT {c}: heat={ev["sector_heat"]} rank={ev["rank"]} strength={ev["strength"]}', flush=True)
