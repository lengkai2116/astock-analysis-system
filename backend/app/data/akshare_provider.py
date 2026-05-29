"""
AkShare实时数据提供者
提供免费的实时行情数据（新浪数据源）
"""
_ak = None
def _get_ak():
    global _ak
    if _ak is None:
        import akshare as ak
        _ak = ak
    return _ak
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional


class AkShareRealtimeProvider:
    """AkShare实时数据提供者"""
    
    def __init__(self):
        self.name = "AkShare"
        self.source = "新浪财经"
    
    def get_realtime_quote(self, ts_code: str) -> Optional[Dict]:
        """
        获取单只股票的实时报价
        
        Args:
            ts_code: 股票代码，如 '600519.SH' 或 '000001.SZ'
            
        Returns:
            包含实时数据的字典，失败返回None
        """
        try:
            # 转换代码格式
            symbol = ts_code.replace('.SH', '').replace('.SZ', '')
            prefix = 'sh' if ts_code.endswith('.SH') else 'sz'
            full_symbol = prefix + symbol
            
            df = _get_ak().stock_bid_ask_em(symbol=symbol)
            if df is None or len(df) == 0:
                return None
            
            # 解析数据
            data = df.set_index('item')['value'].to_dict()
            
            return {
                'ts_code': ts_code,
                'name': self._get_stock_name(ts_code),
                'price': float(data.get('最新', 0)),
                'change': float(data.get('涨跌', 0)),
                'change_pct': float(data.get('涨幅', 0)),
                'open': float(data.get('今开', 0)),
                'high': float(data.get('最高', 0)),
                'low': float(data.get('最低', 0)),
                'prev_close': float(data.get('昨收', 0)),
                'volume': float(data.get('总手', 0)),
                'amount': float(data.get('金额', 0)),
                'bid_price': float(data.get('buy_1', 0)),
                'ask_price': float(data.get('sell_1', 0)),
                'bid_vol': float(data.get('buy_1_vol', 0)),
                'ask_vol': float(data.get('sell_1_vol', 0)),
                'turnover_rate': float(data.get('换手', 0)),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            print(f"❌ 获取 {ts_code} 实时数据失败: {e}")
            return None
    
    def get_realtime_quotes(self, ts_codes: List[str]) -> List[Dict]:
        """
        获取多只股票的实时报价
        
        Args:
            ts_codes: 股票代码列表
            
        Returns:
            实时数据列表
        """
        results = []
        for ts_code in ts_codes:
            data = self.get_realtime_quote(ts_code)
            if data:
                results.append(data)
        return results
    
    def get_index_realtime(self, ts_code: str) -> Optional[Dict]:
        """
        获取指数实时数据
        
        Args:
            ts_code: 指数代码，如 '000001.SH'（上证指数）、'399001.SZ'（深证成指）
        """
        try:
            # 转换代码格式：上证指数000001需要用sh000001，深证成指399001需要用sz399001
            symbol = ts_code.replace('.SH', '').replace('.SZ', '')
            prefix = 'sh' if ts_code.endswith('.SH') else 'sz'
            full_symbol = prefix + symbol
            
            df = _get_ak().stock_bid_ask_em(symbol=full_symbol)
            if df is None or len(df) == 0:
                return None
            
            data = df.set_index('item')['value'].to_dict()
            
            return {
                'ts_code': ts_code,
                'name': self._get_index_name(ts_code),
                'value': float(data.get('最新', 0)),
                'change': float(data.get('涨跌', 0)),
                'change_pct': float(data.get('涨幅', 0)),
                'open': float(data.get('今开', 0)),
                'high': float(data.get('最高', 0)),
                'low': float(data.get('最低', 0)),
                'prev_close': float(data.get('昨收', 0)),
                'volume': float(data.get('总手', 0)),
                'amount': float(data.get('金额', 0)),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            print(f"❌ 获取指数 {ts_code} 实时数据失败: {e}")
            return None
    
    def _get_stock_name(self, ts_code: str) -> str:
        """获取股票名称"""
        name_map = {
            '600519.SH': '贵州茅台',
            '000001.SZ': '平安银行',
            '000002.SZ': '万科A',
            '000858.SZ': '五粮液',
            '000063.SZ': '中兴通讯',
            '601318.SH': '中国平安',
            '600036.SH': '招商银行',
            '000333.SZ': '美的集团',
            '600000.SH': '浦发银行',
            '000002.SZ': '万科A'
        }
        return name_map.get(ts_code, ts_code)
    
    def _get_index_name(self, ts_code: str) -> str:
        """获取指数名称"""
        name_map = {
            '000001.SH': '上证指数',
            '399001.SZ': '深证成指',
            '399006.SZ': '创业板指',
            '000300.SH': '沪深300',
            '000016.SH': '上证50',
            '000905.SH': '中证500'
        }
        return name_map.get(ts_code, ts_code)


if __name__ == '__main__':
    provider = AkShareRealtimeProvider()
    
    print('=== 测试AkShare实时数据 ===\\n')
    
    # 测试单只股票
    print('1. 测试贵州茅台:')
    data = provider.get_realtime_quote('600519.SH')
    if data:
        print(f'   ✅ 成功')
        print(f'   最新价: {data["price"]}')
        print(f'   涨跌幅: {data["change_pct"]}%')
        print(f'   成交额: {data["amount"]/1e6:.2f}百万')
    else:
        print('   ❌ 失败')
    
    # 测试多只股票
    print('\\n2. 测试多只股票:')
    stocks = ['600519.SH', '000001.SZ', '000002.SZ', '601318.SH']
    results = provider.get_realtime_quotes(stocks)
    for r in results:
        print(f'   {r["name"]}({r["ts_code"]}): {r["price"]} ({r["change_pct"]:+.2f}%)')
    
    # 测试指数
    print('\\n3. 测试指数:')
    indices = ['000001.SH', '399001.SZ', '399006.SZ']
    for idx in indices:
        data = provider.get_index_realtime(idx)
        if data:
            print(f'   {data["name"]}: {data["value"]} ({data["change_pct"]:+.2f}%)')
    
    print('\\n=== 测试完成 ===')
