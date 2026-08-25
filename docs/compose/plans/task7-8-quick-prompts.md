# Task 7-8 实现提示

## Task 7: pattern_score_cache 表和 DataManager 接口

### Intent
**[S4] 缓存策略**: 遵循 353/358 号方案架构红线，日终批量计算 + 缓存。

### Files
- Modify: `backend/app/data/__init__.py`
- Create: `backend/tests/test_pattern_score_cache.py`

### 实现要点

1. 在 DataManager 类中添加方法：
```python
def cache_pattern_score(self, ts_code, trade_date, score, details):
    # 实现写入 pattern_score_cache 表
    pass

def get_pattern_score(self, ts_code, trade_date):
    # 实现从 pattern_score_cache 表读取
    return None
```

2. 创建测试验证接口

---

## Task 8: 注册日终批量计算到 data_daemon

### Intent
**[S4] 计算时机**: 遵循 353/358 号方案架构红线，日终批量计算 + 缓存。

### Files
- Modify: `backend/app/data_daemon.py`

### 实现要点

1. 添加批量计算函数：
```python
def _batch_pattern_score(trade_date):
    engine = PatternEngine()
    dm = DataManager()
    stocks = dm.get_all_stocks()
    for ts_code in stocks:
        df = dm.get_daily_kline(ts_code)
        score, details = engine.evaluate(df)
        dm.cache_pattern_score(ts_code, trade_date, score, details)
```

2. 注册到日终同步

## Commit
```bash
git add app/data/__init__.py tests/test_pattern_score_cache.py
git commit -m "feat(data): add pattern_score_cache table and DataManager methods"

git add app/data_daemon.py
git commit -m "feat(daemon): register pattern score batch calculation"
```
