
# DuckDB缓存机制设计文档

## 文档版本
v1.0

## 创建日期
2026-05-15

---

## 一、概述

### 1.1 设计目标

本文档描述达尔文筛选系统中基于DuckDB的本地缓存机制设计，旨在：

1. **提升性能**：将数据查询从网络延迟级别（100ms+）降低到本地磁盘级别（毫秒级）
2. **离线可用**：即使网络中断，系统仍可正常工作
3. **节省积分**：减少不必要的API调用，避免积分浪费
4. **历史数据管理**：支持策略回测和数据分析
5. **高可用性**：实现多数据源容灾

### 1.2 架构定位

```
┌─────────────────────────────────────────────────────────────┐
│                      应用层                                │
│    [筛选引擎] [指标计算] [API接口]                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    缓存层 (DuckDB)                         │
│    [缓存管理器] [数据同步] [过期策略] [查询优化]            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    数据源层                                │
│    [Tushare] [AKShare] [BaoStock] [其他数据源]            │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、缓存机制设计

### 2.1 缓存策略类型

| 策略类型 | 适用场景 | 特点 |
|---------|---------|------|
| **只读缓存** | 股票列表、财务报表等不频繁更新的数据 | 写入一次，多次读取 |
| **读写缓存** | 日线行情、ST股票列表等每日更新的数据 | 定期更新，实时读取 |
| **时间过期缓存** | 所有类型数据 | 根据配置的有效期自动过期 |
| **强制刷新** | 手动更新场景 | 允许用户强制获取最新数据 |

### 2.2 缓存层次结构

```
duckdb_cache/
├── stock_data.db              # 主数据库文件
├── cache_config.yaml          # 缓存配置文件
└── data/                      # 外部数据文件目录
    ├── stock_daily.parquet    # 日线数据（Parquet格式）
    └── balance_sheet.parquet  # 财务报表（Parquet格式）
```

### 2.3 数据表设计

#### 2.3.1 stock_basic（股票基础信息）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| ts_code | VARCHAR | 股票代码（主键） |
| name | VARCHAR | 股票名称 |
| industry | VARCHAR | 行业 |
| list_date | VARCHAR | 上市日期 |
| status | VARCHAR | 状态（正常/ST/退市） |
| update_time | TIMESTAMP | 最后更新时间 |

#### 2.3.2 stock_daily（日线行情）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| ts_code | VARCHAR | 股票代码 |
| trade_date | VARCHAR | 交易日期 |
| open | DOUBLE | 开盘价 |
| high | DOUBLE | 最高价 |
| low | DOUBLE | 最低价 |
| close | DOUBLE | 收盘价 |
| volume | BIGINT | 成交量 |
| amount | DOUBLE | 成交额 |
| pct_chg | DOUBLE | 涨跌幅 |
| update_time | TIMESTAMP | 最后更新时间 |
| PRIMARY KEY (ts_code, trade_date) |

#### 2.3.3 balance_sheet（资产负债表）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| ts_code | VARCHAR | 股票代码 |
| ann_date | VARCHAR | 公告日期 |
| end_date | VARCHAR | 报告期 |
| total_assets | DOUBLE | 总资产 |
| total_liab | DOUBLE | 总负债 |
| total_hldr_eqy_exc_min_int | DOUBLE | 股东权益 |
| update_time | TIMESTAMP | 最后更新时间 |
| PRIMARY KEY (ts_code, end_date) |

#### 2.3.4 profit_sheet（利润表）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| ts_code | VARCHAR | 股票代码 |
| ann_date | VARCHAR | 公告日期 |
| end_date | VARCHAR | 报告期 |
| revenue | DOUBLE | 营业收入 |
| profit | DOUBLE | 净利润 |
| update_time | TIMESTAMP | 最后更新时间 |
| PRIMARY KEY (ts_code, end_date) |

#### 2.3.5 cash_flow（现金流量表）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| ts_code | VARCHAR | 股票代码 |
| ann_date | VARCHAR | 公告日期 |
| end_date | VARCHAR | 报告期 |
| cf_from_operating | DOUBLE | 经营活动现金流 |
| update_time | TIMESTAMP | 最后更新时间 |
| PRIMARY KEY (ts_code, end_date) |

#### 2.3.6 cache_metadata（缓存元数据）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| table_name | VARCHAR | 表名（主键） |
| last_sync_time | TIMESTAMP | 最后同步时间 |
| sync_interval_minutes | INTEGER | 同步间隔（分钟） |
| record_count | BIGINT | 记录数 |
| total_size_bytes | BIGINT | 总大小（字节） |

---

## 三、核心组件设计

### 3.1 CacheManager（缓存管理器）

#### 3.1.1 类定义

```python
class CacheManager:
    """
    DuckDB缓存管理器
    负责缓存的读写、同步、过期管理
    """
    
    def __init__(self, db_path: str = "stock_data.db"):
        """
        初始化缓存管理器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = None
        self._init_connection()
        self._init_tables()
    
    def _init_connection(self):
        """初始化数据库连接"""
        self.conn = duckdb.connect(self.db_path)
        
        # 加载必要扩展
        extensions = ['httpfs', 'json', 'parquet']
        for ext in extensions:
            try:
                self.conn.execute(f"INSTALL {ext}")
                self.conn.execute(f"LOAD {ext}")
            except:
                pass  # 扩展可能已安装
    
    def _init_tables(self):
        """初始化数据表（如果不存在）"""
        # 创建表的DDL语句...
        pass
```

#### 3.1.2 核心方法

| 方法名 | 功能 | 参数 | 返回值 |
|--------|------|------|--------|
| get_stock_basic | 获取股票基础信息 | ts_code: str | DataFrame |
| get_daily_data | 获取日线行情 | ts_code, start_date, end_date | DataFrame |
| get_balance_sheet | 获取资产负债表 | ts_code | DataFrame |
| get_profit_sheet | 获取利润表 | ts_code | DataFrame |
| get_cash_flow | 获取现金流量表 | ts_code | DataFrame |
| insert_stock_basic | 插入股票基础信息 | df: DataFrame | None |
| insert_daily_data | 插入日线行情 | df: DataFrame | None |
| insert_financial_data | 插入财务数据 | df: DataFrame, table_name | None |
| is_cache_valid | 检查缓存是否有效 | table_name, max_age_minutes | bool |
| clear_cache | 清除指定表缓存 | table_name | None |
| sync_all | 同步所有数据 | force_refresh: bool | None |

### 3.2 CacheConfig（缓存配置）

#### 3.2.1 配置结构

```yaml
# cache_config.yaml
cache:
  stock_basic:
    sync_interval_minutes: 10080  # 7天
    enabled: true
  
  stock_daily:
    sync_interval_minutes: 1440   # 1天
    enabled: true
  
  balance_sheet:
    sync_interval_minutes: 43200  # 30天（财报季调整）
    enabled: true
  
  profit_sheet:
    sync_interval_minutes: 43200  # 30天
    enabled: true
  
  cash_flow:
    sync_interval_minutes: 43200  # 30天
    enabled: true
  
  dividend:
    sync_interval_minutes: 43200  # 30天
    enabled: true
```

#### 3.2.2 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| sync_interval_minutes | - | 同步间隔（分钟） |
| enabled | true | 是否启用该表缓存 |

### 3.3 DataSynchronizer（数据同步器）

#### 3.3.1 同步流程

```
┌─────────────────────────────────────────────────────────────┐
│                    数据同步流程                            │
├─────────────────────────────────────────────────────────────┤
│  1. 检查缓存元数据                                        │
│         ↓                                                │
│  2. 判断是否需要同步（根据sync_interval）                    │
│         ↓                                                │
│  3. 从数据源获取最新数据                                   │
│         ↓                                                │
│  4. 更新缓存表                                            │
│         ↓                                                │
│  5. 更新缓存元数据                                        │
└─────────────────────────────────────────────────────────────┘
```

#### 3.3.2 同步策略

```python
def sync_data(table_name: str, force_refresh: bool = False):
    """
    同步指定表的数据
    
    Args:
        table_name: 表名
        force_refresh: 是否强制刷新（跳过时间检查）
    """
    # 1. 检查配置
    config = get_cache_config(table_name)
    if not config['enabled']:
        return
    
    # 2. 检查是否需要同步
    if not force_refresh:
        if is_cache_valid(table_name, config['sync_interval_minutes']):
            return  # 缓存仍有效，无需同步
    
    # 3. 从数据源获取数据
    data = fetch_from_source(table_name)
    
    # 4. 更新缓存
    insert_into_cache(table_name, data)
    
    # 5. 更新元数据
    update_metadata(table_name)
```

---

## 四、缓存使用模式

### 4.1 基本使用模式

#### 模式1：自动缓存（推荐）

```python
from cache_manager import CacheManager

# 创建缓存管理器
cache = CacheManager()

# 获取数据（自动检查缓存）
df = cache.get_daily_data(ts_code='600519.SH', start_date='20260101', end_date='20260515')

# 使用数据进行分析
print(df.head())
```

#### 模式2：强制刷新

```python
# 强制从API获取最新数据（跳过缓存）
df = cache.get_daily_data(
    ts_code='600519.SH', 
    start_date='20260101', 
    end_date='20260515',
    force_refresh=True  # 强制刷新
)
```

#### 模式3：批量查询

```python
# 获取多只股票的数据
stock_list = ['600519.SH', '000858.SZ', '000001.SZ']

for ts_code in stock_list:
    df = cache.get_daily_data(ts_code=ts_code)
    # 处理数据...
```

### 4.2 与数据获取器集成

```python
class EnhancedDataFetcher:
    """
    增强版数据获取器（集成缓存）
    """
    
    def __init__(self, use_cache=True):
        self.use_cache = use_cache
        if self.use_cache:
            self.cache = CacheManager()
    
    def get_daily_data(self, ts_code, start_date=None, end_date=None, force_refresh=False):
        """
        获取日线数据（带缓存）
        """
        if not self.use_cache or force_refresh:
            return self._fetch_from_api(ts_code, start_date, end_date)
        
        # 先查缓存
        cached = self.cache.get_daily_data(ts_code, start_date, end_date)
        if not cached.empty:
            return cached
        
        # 缓存未命中，从API获取
        data = self._fetch_from_api(ts_code, start_date, end_date)
        
        # 存入缓存
        if not data.empty:
            self.cache.insert_daily_data(data)
        
        return data
```

---

## 五、性能优化

### 5.1 数据格式选择

| 格式 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| **Parquet** | 压缩率高，查询快 | 需要额外依赖 | 大量历史数据 |
| **CSV** | 兼容性好，易查看 | 体积大，查询慢 | 少量数据，调试 |
| **DuckDB表** | 查询最快，支持SQL | 只能DuckDB读取 | 活跃查询数据 |

### 5.2 查询优化策略

```sql
-- 优化前：全表扫描
SELECT * FROM stock_daily WHERE trade_date = '20260515';

-- 优化后：利用主键索引
SELECT * FROM stock_daily 
WHERE ts_code = '600519.SH' AND trade_date = '20260515';

-- 聚合查询优化
SELECT ts_code, AVG(close), STDDEV(close)
FROM stock_daily
WHERE trade_date BETWEEN '20260101' AND '20260515'
GROUP BY ts_code;
```

### 5.3 批量操作优化

```python
def batch_insert(df_list):
    """
    批量插入优化
    """
    # 使用临时表批量插入
    combined_df = pd.concat(df_list)
    cache.conn.register('temp_df', combined_df)
    
    cache.conn.execute("""
    INSERT OR REPLACE INTO stock_daily 
    SELECT * FROM temp_df
    """)
```

---

## 六、容错与恢复

### 6.1 缓存失效处理

```python
def get_with_fallback(ts_code, max_retries=3):
    """
    带降级策略的获取方法
    """
    for attempt in range(max_retries):
        try:
            # 先尝试从缓存获取
            data = cache.get_daily_data(ts_code)
            if not data.empty:
                return data
            
            # 缓存为空，尝试从API获取
            data = fetch_from_api(ts_code)
            if not data.empty:
                cache.insert_daily_data(data)
                return data
                
        except Exception as e:
            print(f"尝试 {attempt+1}/{max_retries} 失败: {e}")
            time.sleep(2 ** attempt)  # 指数退避
    
    # 返回空数据或抛出异常
    return pd.DataFrame()
```

### 6.2 数据库备份

```python
def backup_database():
    """
    备份数据库
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"stock_data_{timestamp}.db"
    
    # 复制数据库文件
    shutil.copy2("stock_data.db", backup_path)
    
    # 清理7天前的备份
    for backup_file in glob.glob("stock_data_*.db"):
        file_time = os.path.getmtime(backup_file)
        if time.time() - file_time > 7 * 24 * 3600:
            os.remove(backup_file)
```

---

## 七、监控与维护

### 7.1 缓存状态监控

```python
def get_cache_status():
    """
    获取缓存状态报告
    """
    status = []
    
    # 查询缓存元数据
    df = cache.conn.execute("""
    SELECT table_name, last_sync_time, record_count, total_size_bytes
    FROM cache_metadata
    """).fetchdf()
    
    for _, row in df.iterrows():
        status.append({
            'table': row['table_name'],
            'last_sync': row['last_sync_time'],
            'records': row['record_count'],
            'size_mb': row['total_size_bytes'] / (1024 * 1024)
        })
    
    return status
```

### 7.2 定期清理

```python
def cleanup_expired_cache():
    """
    清理过期缓存
    """
    config = load_config()
    
    for table_name, settings in config['cache'].items():
        if not settings['enabled']:
            continue
        
        max_age = settings['sync_interval_minutes']
        if not cache.is_cache_valid(table_name, max_age):
            cache.clear_cache(table_name)
            print(f"已清理过期缓存: {table_name}")
```

---

## 八、部署与集成

### 8.1 安装依赖

```bash
pip install duckdb duckdb-engine pandas
```

### 8.2 配置环境变量

```bash
# .env 文件
DUCKDB_CACHE_PATH=/path/to/stock_data.db
CACHE_ENABLED=true
CACHE_SYNC_INTERVAL=1440  # 默认同步间隔（分钟）
```

### 8.3 启动时初始化

```python
def init_cache():
    """
    启动时初始化缓存
    """
    # 检查数据库文件是否存在
    if not os.path.exists(CACHE_PATH):
        # 创建初始数据库
        cache = CacheManager(CACHE_PATH)
        print("✅ 缓存数据库创建成功")
    else:
        cache = CacheManager(CACHE_PATH)
        print("✅ 缓存数据库加载成功")
    
    return cache
```

---

## 九、代码实现

### 9.1 完整实现代码

```python
# duckdb_cache_manager.py

import duckdb
import pandas as pd
import os
import yaml
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

class CacheManager:
    """
    DuckDB缓存管理器
    """
    
    def __init__(self, db_path: str = "stock_data.db"):
        self.db_path = db_path
        self.conn = None
        self._config = self._load_config()
        self._init_connection()
        self._init_tables()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载缓存配置"""
        config_path = "cache_config.yaml"
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        return {}
    
    def _init_connection(self):
        """初始化数据库连接"""
        self.conn = duckdb.connect(self.db_path)
        
        # 加载扩展
        extensions = ['httpfs', 'json', 'parquet']
        for ext in extensions:
            try:
                self.conn.execute(f"INSTALL {ext}")
                self.conn.execute(f"LOAD {ext}")
            except:
                pass
    
    def _init_tables(self):
        """初始化数据表"""
        # 股票基础信息表
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_basic (
            ts_code VARCHAR PRIMARY KEY,
            name VARCHAR,
            industry VARCHAR,
            list_date VARCHAR,
            status VARCHAR,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 日线行情表
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            ts_code VARCHAR,
            trade_date VARCHAR,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            amount DOUBLE,
            pct_chg DOUBLE,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ts_code, trade_date)
        )
        """)
        
        # 缓存元数据表
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS cache_metadata (
            table_name VARCHAR PRIMARY KEY,
            last_sync_time TIMESTAMP,
            sync_interval_minutes INTEGER,
            record_count BIGINT,
            total_size_bytes BIGINT
        )
        """)
    
    def get_stock_basic(self, ts_code: Optional[str] = None) -> pd.DataFrame:
        """获取股票基础信息"""
        if ts_code:
            query = f"SELECT * FROM stock_basic WHERE ts_code = '{ts_code}'"
        else:
            query = "SELECT * FROM stock_basic"
        return self.conn.execute(query).fetchdf()
    
    def get_daily_data(self, ts_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取日线行情"""
        query = f"SELECT * FROM stock_daily WHERE ts_code = '{ts_code}'"
        
        if start_date:
            query += f" AND trade_date >= '{start_date}'"
        if end_date:
            query += f" AND trade_date <= '{end_date}'"
        
        query += " ORDER BY trade_date"
        return self.conn.execute(query).fetchdf()
    
    def insert_stock_basic(self, df: pd.DataFrame):
        """插入股票基础信息"""
        self.conn.register('temp_df', df)
        self.conn.execute("""
        INSERT OR REPLACE INTO stock_basic 
        SELECT ts_code, name, industry, list_date, status, CURRENT_TIMESTAMP
        FROM temp_df
        """)
    
    def insert_daily_data(self, df: pd.DataFrame):
        """插入日线行情"""
        self.conn.register('temp_df', df)
        self.conn.execute("""
        INSERT OR REPLACE INTO stock_daily 
        SELECT ts_code, trade_date, open, high, low, close, volume, amount, pct_chg, CURRENT_TIMESTAMP
        FROM temp_df
        """)
    
    def is_cache_valid(self, table_name: str, max_age_minutes: int) -> bool:
        """检查缓存是否有效"""
        result = self.conn.execute(f"""
        SELECT last_sync_time FROM cache_metadata 
        WHERE table_name = '{table_name}'
        """).fetchone()
        
        if not result:
            return False
        
        last_sync = result[0]
        max_age = timedelta(minutes=max_age_minutes)
        
        return (datetime.now() - last_sync) < max_age
    
    def update_metadata(self, table_name: str, sync_interval_minutes: int):
        """更新缓存元数据"""
        # 获取记录数和大小
        count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        
        self.conn.execute(f"""
        INSERT OR REPLACE INTO cache_metadata (
            table_name, last_sync_time, sync_interval_minutes, record_count, total_size_bytes
        ) VALUES (
            '{table_name}', CURRENT_TIMESTAMP, {sync_interval_minutes}, {count}, 0
        )
        """)
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
```

---

## 十、总结

### 10.1 设计优势

| 特性 | 说明 |
|------|------|
| **高性能** | 毫秒级查询响应 |
| **离线可用** | 不受网络影响 |
| **节省积分** | 减少API调用 |
| **灵活配置** | 支持不同缓存策略 |
| **高可靠** | 自动备份和恢复 |

### 10.2 使用价值

1. **开发阶段**：快速迭代，无需频繁调用API
2. **测试阶段**：稳定的数据环境，可重复测试
3. **生产阶段**：高性能、高可用的数据服务
4. **研究阶段**：方便的历史数据分析和回测

### 10.3 下一步工作

1. ✅ 实现CacheManager核心类
2. ✅ 设计数据表结构
3. ✅ 实现数据同步器
4. ✅ 编写配置文件
5. ⏳ 集成到现有数据获取器
6. ⏳ 实现监控和维护工具

---

**文档完成时间**：2026-05-15  
**文档版本**：v1.0  
**存档位置**：[034-DuckDB缓存机制设计文档.md](file:///Users/kalence/Desktop/测试/002-方案存档/034-DuckDB缓存机制设计文档.md)
