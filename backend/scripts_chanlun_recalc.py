"""V2 risk_level/support_resistance 落库：并行计算+串行写（避免 SQLite 写锁竞争）

multiprocessing 8 进程只算缠论信号（读 K 线），主进程串行写 strategy_signal_detail。
"""
import os, sys, time
sys.path.insert(0, '/Users/kalence/Desktop/01-A股股票分析系统/backend')
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)
from multiprocessing import Pool

def _compute(code):
    try:
        from app.services.signal_computation_service import SignalComputationService
        from app.data import DataManager
        dm = DataManager()
        df = dm.get_cached_daily_data(code)
        if df is None or df.empty:
            return None
        sig = SignalComputationService()._compute_chanlun_signal(code, df)
        if not sig:
            return None
        sr = sig.get('status_recognition', {})
        # 返回序列化结果（避免跨进程传对象）
        import json
        return (code, sig.get('trade_date', ''), sig.get('strategy_name', '缠论走势分析'),
                json.dumps(sig, ensure_ascii=False, default=str))
    except Exception:
        return None

if __name__ == '__main__':
    from app.data import DataManager
    import json as _json
    dm = DataManager()
    codes = [r[0] for r in dm.cache.conn.execute("SELECT DISTINCT ts_code FROM daily_cache").fetchall()]
    print(f'待处理: {len(codes)} 只（8 进程计算 + 串行写）', flush=True)
    t0 = time.time()
    dist = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    written = 0
    batch = []
    with Pool(8) as pool:
        for i, res in enumerate(pool.imap_unordered(_compute, codes, chunksize=20)):
            if res:
                code, td, name, sig_json = res
                # 读现有 signals，替换缠论
                cached = dm.cache.get_latest_signal_detail(code) or {}
                signals = cached.get('signals', {})
                chan_key = None
                for k in signals:
                    if '缠论' in k:
                        chan_key = k
                        break
                sig_dict = _json.loads(sig_json)
                if chan_key:
                    signals[chan_key] = sig_dict
                else:
                    signals[name] = sig_dict
                batch.append((code, {'signals': signals, 'trade_date': td}))
                rl = sig_dict.get('status_recognition', {}).get('risk_level')
                if rl:
                    dist[rl] = dist.get(rl, 0) + 1
            if len(batch) >= 200:
                for code, rd in batch:
                    dm.cache.cache_signal_detail(code, rd)
                    written += 1
                batch = []
                print(f'  进度 {i+1}/{len(codes)} 写 {written} {dist}', flush=True)
        if batch:
            for code, rd in batch:
                dm.cache.cache_signal_detail(code, rd)
                written += 1
    print(f'完成: 写 {written}/{len(codes)}, 耗时 {(time.time()-t0)/60:.1f} 分钟, risk_level: {dist}', flush=True)
