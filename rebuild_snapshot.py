#!/usr/bin/env python3
"""重建快照（新版 _build_treemap_snapshot）"""
import os, sys
sys.path.insert(0, '/Users/kalence/Desktop/01-A股股票分析系统/backend')
os.environ.setdefault('DATA_DIR', '/Users/kalence/Desktop/01-A股股票分析系统/data')

from app.data.enhanced_cache_manager import EnhancedCacheManager
import data_daemon as dd

ecm = EnhancedCacheManager()
dd._ecm = ecm
codes = ecm._query_df("SELECT ts_code FROM treemap_snapshot")["ts_code"].tolist()
print(f"重建快照: {len(codes)} 只...", flush=True)
dd._build_treemap_snapshot(codes)
cols = [r[1] for r in ecm.conn.execute("PRAGMA table_info(treemap_snapshot)").fetchall()]
print("快照列数:", len(cols), "含 presence_evidence:", 'presence_evidence' in cols, flush=True)
print("快照行数:", ecm.conn.execute("SELECT COUNT(*) FROM treemap_snapshot").fetchone()[0], flush=True)
print("完成 ✅", flush=True)
