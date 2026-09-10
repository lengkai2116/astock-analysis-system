"""调试 dim4 完整 evaluate 输出"""
import sys
sys.path.insert(0, "/Users/kalence/Desktop/01-A股股票分析系统/backend")

from flask import Flask
from app import db
from app.data import DataManager
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import Dim4ChipFundEngine

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////Users/kalence/Desktop/01-A股股票分析系统/data/app.db'
db.init_app(app)

with app.app_context():
    dm = DataManager()
    ts_code = "600519.SH"
    df = dm.get_cached_daily_data(ts_code)
    pre_feat = dm.get_pre_feat(ts_code)
    # 展平 tags（模拟 dim1 的 _flatten_pre_feat）
    tags = {}
    for gname, gdata in pre_feat.items():
        if isinstance(gdata, dict):
            for k, v in gdata.items():
                if v is not None:
                    tags[k] = v
    tags['ts_code'] = ts_code

    data_context = {
        'daily_df': df,
        'chip_fund_ext': pre_feat.get('chip_fund_ext'),
        'moneyflow_df': dm.get_cached_moneyflow(ts_code),
    }

    engine = Dim4ChipFundEngine()
    result = engine.evaluate({}, tags, data_context=data_context)
    print("status_description:", result['status_description'])
    print("judgment:", result['judgment'])
    print("audit:", result['audit'])
