"""488-2 单测：涨跌停情绪池采集修复（AKShare 官方接口 + 列名映射 + ts_code 归一）

覆盖：
  - _pool_ts_code：6→SH / 0,3→SZ / 4,8→BJ / 9→SH(B股) / 空
  - _pool_int：''/None/nan/0 → default
  - _collect_sentiment_pool：调用官方两接口（date= 关键字）、涨停池/跌停池映射、
    连续板数字段分流（连板数 vs 连续跌停）、reason_category 回退所属行业、写入记录
  - backfill_sentiment_pool：多日循环累计
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from unittest import mock

import pandas as pd
from app.data import akshare_collector as akc
from app.data.akshare_collector import (
    _collect_sentiment_pool,
    _pool_int,
    _pool_ts_code,
    backfill_sentiment_pool,
)

_UP_COLS = ['序号', '代码', '名称', '涨跌幅', '最新价', '成交额', '流通市值', '总市值',
            '换手率', '封板资金', '首次封板时间', '最后封板时间', '炸板次数',
            '涨停统计', '连板数', '所属行业']
_DOWN_COLS = ['序号', '代码', '名称', '涨跌幅', '最新价', '成交额', '流通市值', '总市值',
              '动态市盈率', '换手率', '封单资金', '最后封板时间', '板上成交额',
              '连续跌停', '开板次数', '所属行业']


def _up_df():
    return pd.DataFrame([
        ['1', '000498', '山东路桥', 9.92, 5.65, 314302752, 8188814951.35, 8771297480.8,
         3.84, 59982095, '092500', '093136', 1, '1/1', 1, '基础建设'],
        ['2', '600000', '浦发银行', 10.01, 9.34, 1e8, 2e9, 3e9,
         1.2, 1e7, '093000', '150000', 0, '2/2', 2, '银行'],
        ['3', '830799', '艾能聚', 29.97, 12.0, 1e7, 4e8, 5e8,
         2.0, 1e6, '100000', '100000', 0, '1/1', 1, '光伏设备'],
    ], columns=_UP_COLS)


def _down_df():
    return pd.DataFrame([
        ['1', '000607', '华媒控股', -10.04, 4.03, 488481952, 3566800537.04, 4101324616.48,
         -127.9, 13.42, 1981083, '150000', 411448345, 2, 4, '广告营销'],
    ], columns=_DOWN_COLS)


_ZHA_COLS = ['序号', '代码', '名称', '涨跌幅', '最新价', '涨停价', '成交额', '流通市值',
             '总市值', '换手率', '涨速', '首次封板时间', '炸板次数', '涨停统计', '振幅', '所属行业']


def _zha_df():
    return pd.DataFrame([
        ['1', '000910', '大亚圣象', 0.26, 7.6, 8.34, 840876512, 4158986950.0,
         4160221030.4, 19.1, 0.0, '093000', 2, '5/4', 12.0, '家居用品'],
        ['2', '600111', '北方稀土', 1.5, 30.0, 32.0, 1e8, 2e9,
         3e9, 5.0, 0.0, '100000', 1, '1/1', 8.0, '小金属'],
    ], columns=_ZHA_COLS)


class TestPureHelpers:

    def test_ts_code_mapping(self):
        assert _pool_ts_code('600000') == '600000.SH'
        assert _pool_ts_code('000001') == '000001.SZ'
        assert _pool_ts_code('300750') == '300750.SZ'
        assert _pool_ts_code('830799') == '830799.BJ'
        assert _pool_ts_code('430047') == '430047.BJ'
        assert _pool_ts_code('900901') == '900901.SH'
        assert _pool_ts_code('') == ''

    def test_pool_int(self):
        assert _pool_int('2') == 2
        assert _pool_int(3) == 3
        assert _pool_int('') == 1
        assert _pool_int(None) == 1
        assert _pool_int('nan') == 1
        assert _pool_int('0') == 1          # 0 视为无连板 → default
        assert _pool_int('2.0') == 2


class TestCollect:

    def _fake_ak(self):
        ak = mock.MagicMock()
        ak.stock_zt_pool_em.return_value = _up_df()
        ak.stock_zt_pool_dtgc_em.return_value = _down_df()
        ak.stock_zt_pool_zbgc_em.return_value = _zha_df()
        return ak

    def test_collect_maps_official_endpoints(self):
        ak = self._fake_ak()
        ecm = mock.MagicMock()
        with mock.patch.object(akc, '_get_ak', return_value=ak), \
             mock.patch.object(akc, '_get_ecm', return_value=ecm):
            n = _collect_sentiment_pool('2026-09-24')

        # 官方接口按 date= 调用（原 bug：market=/type=）
        ak.stock_zt_pool_em.assert_called_once_with(date='20260924')
        ak.stock_zt_pool_dtgc_em.assert_called_once_with(date='20260924')
        ak.stock_zt_pool_zbgc_em.assert_called_once_with(date='20260924')
        assert n == 6                        # 3 涨停 + 1 跌停 + 2 炸板
        ecm.write_sentiment_pool.assert_called_once()
        recs = ecm.write_sentiment_pool.call_args[0][0]
        up = [r for r in recs if r['limit_type'] == 'up']
        down = [r for r in recs if r['limit_type'] == 'down']
        zha = [r for r in recs if r['limit_type'] == 'zha']
        assert len(up) == 3 and len(down) == 1 and len(zha) == 2
        assert {r['ts_code'] for r in up} == {'000498.SZ', '600000.SH', '830799.BJ'}
        # 涨停池：连板数 → consecutive_days；reason_category 回退「所属行业」
        assert up[1]['consecutive_days'] == 2 and up[1]['reason_category'] == '银行'
        assert up[0]['first_seal_time'] == '092500'
        assert up[0]['trade_date'] == '20260924'
        # 跌停池：连续跌停 → consecutive_days；无首次封板时间
        assert down[0]['ts_code'] == '000607.SZ'
        assert down[0]['consecutive_days'] == 2
        assert down[0]['first_seal_time'] == ''
        # 炸板池（488-2 封板率分母）：无「连板数」列 → default 1；有首次封板时间
        assert {r['ts_code'] for r in zha} == {'000910.SZ', '600111.SH'}
        assert zha[0]['consecutive_days'] == 1
        assert zha[0]['first_seal_time'] == '093000'

    def test_missing_endpoint_skipped(self):
        ak = self._fake_ak()
        ak.stock_zt_pool_dtgc_em = None   # 模拟旧版 akshare 无跌停池接口
        ecm = mock.MagicMock()
        with mock.patch.object(akc, '_get_ak', return_value=ak), \
             mock.patch.object(akc, '_get_ecm', return_value=ecm):
            n = _collect_sentiment_pool('20260924')
        assert n == 5                     # 3 涨停 + 2 炸板（跌停池缺接口）
        recs = ecm.write_sentiment_pool.call_args[0][0]
        assert {r['limit_type'] for r in recs} == {'up', 'zha'}

    def test_backfill_loops_dates(self):
        ak = self._fake_ak()
        ecm = mock.MagicMock()
        with mock.patch.object(akc, '_get_ak', return_value=ak), \
             mock.patch.object(akc, '_get_ecm', return_value=ecm):
            total = backfill_sentiment_pool(['20260922', '2026-09-23'])
        assert total == 12                # 2 日 × 6 条
        assert ak.stock_zt_pool_em.call_count == 2


class TestSentimentServiceSealingRate:
    """488-2：封板率口径 = 涨停/(涨停+炸板)；无炸板数据回退原口径"""

    class _FakeDM:
        def __init__(self, df):
            self._df = df

        def get_cached_sentiment_pool(self, trade_date=None):
            return self._df

    @staticmethod
    def _pool_table(up: int, down: int, zha: int) -> pd.DataFrame:
        """表结构样本（sentiment_pool_cache 列：trade_date/ts_code/limit_type/
        consecutive_days/first_seal_time）"""
        rows = []
        for i in range(up):
            rows.append({'trade_date': '20260924', 'ts_code': f'60000{i}.SH',
                         'limit_type': 'up', 'consecutive_days': 2 if i == 0 else 1,
                         'first_seal_time': '093000'})
        for i in range(down):
            rows.append({'trade_date': '20260924', 'ts_code': f'00000{i}.SZ',
                         'limit_type': 'down', 'consecutive_days': 1,
                         'first_seal_time': ''})
        for i in range(zha):
            rows.append({'trade_date': '20260924', 'ts_code': f'30000{i}.SZ',
                         'limit_type': 'zha', 'consecutive_days': 1,
                         'first_seal_time': '093000'})
        return pd.DataFrame(rows)

    def _svc(self, df):
        from app.services.market_sentiment_service import MarketSentimentService
        return MarketSentimentService(data_manager=self._FakeDM(df))

    def test_prefers_zha_denominator(self):
        r = self._svc(self._pool_table(up=3, down=1, zha=2)).get_sentiment_phase('20260924')
        assert r['data_available'] is True
        m = r['metrics']
        assert m['limit_up_count'] == 3 and m['limit_down_count'] == 1
        assert m['sealing_rate'] == round(3 / (3 + 2) * 100, 1)   # 60.0
        assert m['max_board_height'] == 2

    def test_fallback_without_zha(self):
        # 无炸板行 → 回退「首次封板时间比例」（样本全封板 → 100.0）
        r = self._svc(self._pool_table(up=3, down=1, zha=0)).get_sentiment_phase('20260924')
        assert r['metrics']['sealing_rate'] == 100.0


class TestDim8MarketStateSentence:
    """488-2：dim8「大盘状态」句涨停家数/封板率改读 emotion_ext（原读 market_stats 恒不出句）"""

    def _dc(self, ee):
        return {'signal': {'data_context': {'market_stats': {'ma20_ratio': 0.39},
                                            'emotion_ext': ee}}}

    def test_includes_limit_up_and_sealing(self):
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _market_state_sentence
        s = _market_state_sentence(self._dc({'limit_up_count': 52, 'sealing_rate': 83.9}))
        assert '大盘状态：全市场20日均线强势占比39%（偏弱）' in s or '全市场MA20强势占比39%' in s
        assert '涨停52家' in s
        assert '封板率84%' in s

    def test_degrade_without_pool(self):
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _market_state_sentence
        s = _market_state_sentence(self._dc({}))
        assert '涨停' not in s and '封板率' not in s   # 缺则降级（437 标准）


