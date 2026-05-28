"""
QMT行情数据提供者 - 集成招商证券miniQMT实时行情
"""
import time
import threading
from typing import List, Dict, Optional, Callable
from datetime import datetime

try:
    from xtquant import xtdata
    QMT_AVAILABLE = True
except ImportError:
    QMT_AVAILABLE = False


class QmtDataProvider:
    """QMT行情数据提供者"""
    
    def __init__(self):
        self._callbacks = {}
        self._seq_map = {}
        self._running = False
        self._thread = None
        self._qmt_connected = False
        
    def connect(self) -> bool:
        """连接到miniQMT"""
        if not QMT_AVAILABLE:
            print("❌ xtquant库未安装")
            return False
            
        try:
            xtdata.connect()
            self._qmt_connected = True
            print("✅ 成功连接到miniQMT")
            return True
        except Exception as e:
            print(f"❌ 连接miniQMT失败: {e}")
            return False
    
    def disconnect(self):
        """断开连接"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        
        for seq in list(self._seq_map.keys()):
            self.unsubscribe(seq)
        
        self._qmt_connected = False
        print("✅ 已断开miniQMT连接")
    
    def subscribe_tick(self, stock_codes: List[str], callback: Callable) -> int:
        """订阅Tick数据"""
        if not self._qmt_connected:
            print("❌ 请先连接miniQMT")
            return -1
        
        try:
            seq = xtdata.subscribe_whole_quote(
                code_list=stock_codes,
                callback=callback
            )
            if seq > 0:
                self._seq_map[seq] = {'type': 'tick', 'codes': stock_codes, 'callback': callback}
                print(f"✅ 成功订阅Tick数据，订阅号: {seq}")
            return seq
        except Exception as e:
            print(f"❌ 订阅失败: {e}")
            return -1
    
    def subscribe_kline(self, stock_codes: List[str], period: str = '1m', 
                       callback: Optional[Callable] = None) -> Dict[str, int]:
        """订阅K线数据"""
        if not self._qmt_connected:
            print("❌ 请先连接miniQMT")
            return {}
        
        results = {}
        for code in stock_codes:
            try:
                seq = xtdata.subscribe_quote(
                    stock_code=code,
                    period=period,
                    count=0,
                    callback=callback
                )
                if seq > 0:
                    results[code] = seq
                    self._seq_map[seq] = {'type': 'kline', 'code': code, 'period': period}
                    print(f"✅ 成功订阅 {code} {period} K线，订阅号: {seq}")
            except Exception as e:
                print(f"❌ 订阅 {code} 失败: {e}")
                results[code] = -1
        
        return results
    
    def unsubscribe(self, seq: int):
        """取消订阅"""
        try:
            xtdata.unsubscribe_quote(seq)
            if seq in self._seq_map:
                del self._seq_map[seq]
            print(f"✅ 已取消订阅，订阅号: {seq}")
        except Exception as e:
            print(f"❌ 取消订阅失败: {e}")
    
    def get_tick(self, stock_codes: List[str]) -> Dict:
        """获取最新Tick数据"""
        if not self._qmt_connected:
            return {}
        
        try:
            data = xtdata.get_full_tick(stock_codes)
            return data
        except Exception as e:
            print(f"❌ 获取Tick数据失败: {e}")
            return {}
    
    def get_kline(self, stock_code: str, period: str = '1d', 
                 start_time: str = '', end_time: str = '', count: int = -1) -> Optional[Dict]:
        """获取历史K线数据"""
        if not self._qmt_connected:
            return None
        
        try:
            data = xtdata.get_market_data(
                stock_code=stock_code,
                period=period,
                start_time=start_time,
                end_time=end_time,
                count=count
            )
            return data
        except Exception as e:
            print(f"❌ 获取K线数据失败: {e}")
            return None
    
    def get_market_snapshot(self, stock_codes: List[str]) -> List[Dict]:
        """获取市场快照"""
        if not self._qmt_connected:
            return []
        
        try:
            tick_data = self.get_tick(stock_codes)
            results = []
            
            for code, data in tick_data.items():
                results.append({
                    'ts_code': code,
                    'price': data.get('lastPrice', 0),
                    'open': data.get('openPrice', 0),
                    'high': data.get('highPrice', 0),
                    'low': data.get('lowPrice', 0),
                    'prev_close': data.get('preClosePrice', 0),
                    'volume': data.get('volume', 0),
                    'amount': data.get('turnover', 0),
                    'bid_price': data.get('bidPrice1', 0),
                    'ask_price': data.get('askPrice1', 0),
                    'bid_volume': data.get('bidVolume1', 0),
                    'ask_volume': data.get('askVolume1', 0),
                    'timestamp': datetime.now().isoformat()
                })
            
            return results
        except Exception as e:
            print(f"❌ 获取市场快照失败: {e}")
            return []
    
    def run(self, background: bool = True):
        """启动行情接收循环"""
        if not self._qmt_connected:
            print("❌ 请先连接miniQMT")
            return
        
        self._running = True
        
        if background:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            print("✅ 行情接收线程已启动")
        else:
            self._run_loop()
    
    def _run_loop(self):
        """内部运行循环"""
        try:
            xtdata.run()
        except Exception as e:
            print(f"❌ 行情循环异常: {e}")
        finally:
            self._running = False


if __name__ == '__main__':
    provider = QmtDataProvider()
    
    if provider.connect():
        snapshot = provider.get_market_snapshot(['600519.SH', '000001.SZ'])
        for stock in snapshot:
            print(f"{stock['ts_code']}: {stock['price']}")
        
        def on_tick(datas):
            for code, data in datas.items():
                print(f"[{datetime.now()}] {code}: {data.get('lastPrice')}")
        
        seq = provider.subscribe_tick(['600519.SH', '000001.SZ'], on_tick)
        
        provider.run(background=False)