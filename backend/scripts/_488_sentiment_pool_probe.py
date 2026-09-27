"""488号 附2：sentiment_pool_cache 供给核查（只读）

用途：488 A1 复跑发现 emotion_ext 无 limit_up_count/sealing_rate →
      上游 `ms.get_sentiment_phase()` 依赖 `sentiment_pool_cache`；核查该表覆盖与
      `data_available` 状态（区分采集缺口 / 接线缺口）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app import create_app


def main():
    app = create_app()
    with app.app_context():
        from app.services.market_sentiment_service import MarketSentimentService
        ms = MarketSentimentService()
        dm = ms.data_manager
        for d in ['20260924', '20260923', '20260922', '20260927']:
            try:
                df = dm.get_cached_sentiment_pool(d)
                n = 0 if df is None else len(df)
            except Exception as e:
                n = f'ERR {e}'
            r = ms.get_sentiment_phase(d)
            print(f'{d}: rows={n} data_available={r.get("data_available")} '
                  f'phase={r.get("phase")} metrics={r.get("metrics")}')


if __name__ == '__main__':
    main()
