#!/usr/bin/env python3
"""
全量股票数据同步脚本

分批同步 A 股股票日线/分钟线/财务数据，支持断点续传。
Tushare Pro 5000 积分权限全开。

用法:
    python scripts/sync_stocks.py                              # 全量日线同步
    python scripts/sync_stocks.py --type minute                # 分钟线
    python scripts/sync_stocks.py --type fina                  # 财务指标
    python scripts/sync_stocks.py --start 2026-01-01           # 指定起始日期
    python scripts/sync_stocks.py --batch-size 50              # 每批 50 只
    python scripts/sync_stocks.py --resume                     # 断点续传
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

# 确保能找到 backend 包
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

# 加载 .env
from dotenv import load_dotenv
load_dotenv()

import tushare as ts

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(
            os.environ.get('DATA_DIR', 'data'), 'logs', 'sync_stocks.log'
        ))
    ]
)
logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'))
PROGRESS_FILE = os.path.join(DATA_DIR, '.sync_progress.json')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Tushare 频率控制: 200 次/分钟 → 每 0.3 秒一次
TUSHARE_DELAY = 0.3


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {'last_index': 0, 'completed': []}


def save_progress(index: int, ts_code: str):
    progress = load_progress()
    progress['last_index'] = index
    if ts_code not in progress['completed']:
        progress['completed'].append(ts_code)
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def sync_daily(pro, stocks, start_date, batch_size):
    """同步日线行情"""
    total = len(stocks)
    start_index = load_progress()['last_index']

    logger.info(f"开始日线同步: {total} 只, 起始 {start_date}, 从第 {start_index} 只续传")

    for i in range(start_index, total, batch_size):
        batch = stocks[i:i + batch_size]
        for stock in batch:
            ts_code = stock['ts_code']
            try:
                df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=datetime.now().strftime('%Y%m%d'))
                logger.info(f"[{i+1}/{total}] {ts_code} {stock.get('name','')}: {len(df)} 条")
                save_progress(i + 1, ts_code)
                time.sleep(TUSHARE_DELAY)
            except Exception as e:
                logger.error(f"[{i+1}/{total}] {ts_code} 失败: {e}")
                time.sleep(1)

    logger.info("日线同步完成")


def sync_minute(pro, stocks, start_date, batch_size):
    """同步分钟线（需 6000 分，暂不可用时会跳过）"""
    total = len(stocks)
    start_index = load_progress()['last_index']

    logger.info(f"开始分钟线同步: {total} 只")
    skipped = 0

    for i in range(start_index, total, batch_size):
        batch = stocks[i:i + batch_size]
        for stock in batch:
            ts_code = stock['ts_code']
            try:
                df = pro.stk_mins(ts_code=ts_code, start_date=start_date, end_date=datetime.now().strftime('%Y%m%d'), freq='5min')
                logger.info(f"[{i+1}/{total}] {ts_code}: {len(df)} 条分钟线")
                save_progress(i + 1, ts_code)
                time.sleep(TUSHARE_DELAY)
            except Exception as e:
                if '权限' in str(e) or '积分' in str(e):
                    skipped += 1
                    if skipped == 1:
                        logger.warning(f"{ts_code} 无权限（可能是积分不足），跳过分钟线")
                    save_progress(i + 1, ts_code)
                else:
                    logger.error(f"[{i+1}/{total}] {ts_code} 失败: {e}")
                    time.sleep(1)

    logger.info(f"分钟线同步完成（跳过 {skipped} 只）")


def sync_fina(pro, stocks, start_date, batch_size):
    """同步财务指标（5000 分可用）"""
    total = len(stocks)
    start_index = load_progress()['last_index']

    logger.info(f"开始财务数据同步: {total} 只")

    for i in range(start_index, total, batch_size):
        batch = stocks[i:i + batch_size]
        for stock in batch:
            ts_code = stock['ts_code']
            try:
                # 财务指标
                df = pro.fina_indicator_vip(ts_code=ts_code, start_date=start_date)
                logger.info(f"[{i+1}/{total}] {ts_code}: {len(df)} 条财务指标")
                save_progress(i + 1, ts_code)
                time.sleep(TUSHARE_DELAY)
            except Exception as e:
                logger.error(f"[{i+1}/{total}] {ts_code} 财务指标失败: {e}")
                time.sleep(1)

    logger.info("财务数据同步完成")


def main():
    parser = argparse.ArgumentParser(description='A股全量股票数据同步')
    parser.add_argument('--type', choices=['daily', 'minute', 'fina'], default='daily',
                        help='同步类型: daily(日线) / minute(分钟) / fina(财务)')
    parser.add_argument('--start', type=str, default=None,
                        help='起始日期 YYYYMMDD，默认 90 天前')
    parser.add_argument('--batch-size', type=int, default=50,
                        help='每批股票数量')
    parser.add_argument('--resume', action='store_true',
                        help='断点续传（从上次中断位置继续）')
    args = parser.parse_args()

    token = os.environ.get('TUSHARE_TOKEN', '')
    if not token:
        logger.error("TUSHARE_TOKEN 未设置，请在 .env 中配置")
        sys.exit(1)

    ts.set_token(token)
    pro = ts.pro_api()

    # 获取全量股票列表
    logger.info("获取股票列表...")
    df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,list_date')
    stocks = df.to_dict('records')
    logger.info(f"共 {len(stocks)} 只股票")

    if not args.resume:
        # 非续传模式，清空进度
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)

    start_date = args.start or (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')

    sync_fns = {
        'daily': sync_daily,
        'minute': sync_minute,
        'fina': sync_fina,
    }

    sync_fns[args.type](pro, stocks, start_date, args.batch_size)


if __name__ == '__main__':
    main()
