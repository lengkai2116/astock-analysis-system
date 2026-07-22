# P5: 数据缺失静默跳过修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task.

**Goal:** 在 signal_computation_service.py 的 12 处 DATA_FETCH 静默回退位置前插入 `DataManager.request_data()` 调用，使数据缺失时信号到达 daemon 异步补采队列，代替当前的静默 `pass`/`debug log`。

**Architecture:** 在 catch 块中 data fetch 失败后、silent fallback 之前，调用 `self.data_manager.request_data(task_type, ts_code)` 写入 sync_requests 表。保留现有 fallback 行为不变（空值/降级），用户无感知。

**Tech Stack:** Python 3.10+, existing DataManager API

---

## 现有基础设施

### DataManager API（`backend/app/data/__init__.py:1517`）
```python
def request_data(self, task_type: str, ts_code: str = None) -> int:
    """数据缺失时写 sync_requests 队列表，通知 daemon 异步补采"""
    return self.cache.request_data(task_type, ts_code)
```

### 已有 task_types（daemon 端 `data_daemon.py:1532-1550`）
| task_type | daemon handler | 适合场景 |
|-----------|---------------|----------|
| `full_daily` | `_batch_daily` + `_batch_daily_basic` | 全市场日线 |
| `full_moneyflow` | `_batch_moneyflow` | 全市场资金流向 |
| `full_basic` | `_batch_daily_basic` | 全市场基本面 |
| `full_stock_list` | `_batch_stock_list` | 股票列表 |
| `per_stock` | `_batch_daily` | 单只股票日线 |
| `adj_factor` | `_batch_adj_factor` | 复权因子 |
| `top10_holders` | `_batch_top10_holders` | 十大股东 |
| `stk_holder` | `_batch_stk_holder` | 股东户数 |
| `finance_report` | `_batch_finance_report` | 财务报告 |

### 需要新增的 task_types（daemon 消费端 + 调用）
| task_type | 新增在 daemon 的处理 | 本计划的调用位置 |
|-----------|---------------------|-----------------|
| `margin` | `_batch_margin` | P5#5 (margin数据) |
| `concept` | `_batch_concept` | P5#9 (板块概念) |
| `index_daily` | 暂不新增（日终已覆盖） | P5#4, #6 |
| `factor_precompute` | 暂不新增 | P5#12 |
| `news_sentiment` | 暂不新增 | P5#7 |

> 不是每个缺失都要新增 daemon handler — 日终 15:30 的批量同步已覆盖所有数据。`request_data()` 调用主要作用是**信号化**：让 daemon 知道有数据缺口。
> 对于 index/concept/news/factor，daemon 已在日终同步或 1800s 轮询中采集，新增 handler 不是本计划范围。

---

## 数据类别映射

| # | 位置(行) | 缺失数据类型 | task_type | Daemon handler |
|---|----------|-------------|-----------|----------------|
| 1 | 879-883 | moneyflow | `full_moneyflow` | ✅ 已存在 |
| 2 | 906-922 | daily_basic | `full_basic` | ✅ 已存在 |
| 3 | 957-971 | moneyflow | `full_moneyflow` | ✅ 已存在 |
| 4 | 974-1000 | HS300 index | — | 日终覆盖，不新增 |
| 5 | 1061-1090 | margin | `margin` | ⬆ 新增 |
| 6 | 1199-1202 | HS300 index | — | 日终覆盖，不新增 |
| 7 | 1246-1265 | news | — | 日终覆盖，不新增 |
| 8 | 1484-1491 | top10_holders | `top10_holders` | ✅ 已存在 |
| 9 | 1548-1553 | concept | `concept` | ⬆ 新增 |
| 10 | 1657-1673 | multi kline | `per_stock` | ✅ 已存在 |
| 11 | 704-748 | top10/stk_holder | `top10_holders`+`stk_holder` | ✅ 已存在 |
| 12 | 2419-2440 | factor | — | 日终覆盖，不新增 |

---

## 任务分解

### Task 1: 新增 daemon 端 task_type handler

**Files:**
- Modify: `backend/data_daemon.py:1549-1550`（在 finance_report 之后新增 margin + concept 分支）

- [ ] **Step 1: 添加 margin 和 concept 分支**

  在 `data_daemon.py` 的 sync_requests 消费循环中，`finance_report` 分支之后添加：
  ```python
  elif req['task_type'] == 'margin':
      _batch_margin(datetime.now().strftime('%Y%m%d'))
  elif req['task_type'] == 'concept':
      _batch_concept()
  ```

### Task 2: 修复 signal_computation_service.py 的 12 处 DATA_FETCH

**Files:**
- Modify: `backend/app/services/signal_computation_service.py`（12处添加 request_data 调用）

- [ ] **Step 1: #1 资金流向检查（L879-883）**

  ```python
  # 原代码：
  except Exception:
      pass
  
  # 改为：
  except Exception:
      self.data_manager.request_data('full_moneyflow', ts_code)
  ```

- [ ] **Step 2: #2 daily_basic 加载（L906-922）**

  ```python
  # 在 except 中 else 分支前（约 L921）添加：
  except Exception as e:
      logger.debug(f"{ts_code} daily_basic 加载跳过: {e}")
      self.data_manager.request_data('full_basic', ts_code)  # ← 新增
  ```

- [ ] **Step 3: #3 资金流向加载（L957-971）**

  ```python
  # 在 except 中添加：
  except Exception as e:
      logger.debug(f"{ts_code} 资金流向加载跳过: {e}")
      self.data_manager.request_data('full_moneyflow', ts_code)  # ← 新增
  ```

- [ ] **Step 4: #4 大盘环境加载（L974-1000）**

  ```python
  # 在 except 中添加：
  except Exception as e:
      logger.debug(f"{ts_code} 大盘环境加载跳过: {e}")
      # 大盘指数数据日终 15:30 同步覆盖
  ```

- [ ] **Step 5: #5 融资余额加载（L1061-1090）**

  ```python
  # 在 except 中添加：
  except Exception:
      self.data_manager.request_data('margin', ts_code)  # ← 新增
      market_context['sentiment_crowding'] = None
  ```

- [ ] **Step 6: #6 BOCIASI 指数（L1199-1202）**

  ```python
  # 在 except 中添加：
  except Exception:
      index_data = None
      # 指数数据日终同步覆盖
  ```

- [ ] **Step 7: #7 新闻情绪（L1246-1265）**

  ```python
  # 在 except 中添加（不需要 ts_code 的场景）：
  except Exception as e:
      logger.debug(f"{ts_code} 新闻情绪修正跳过: {e}")
  ```

- [ ] **Step 8: #8 主力成本（L1484-1491）**

  ```python
  # 在 except 中添加：
  except Exception:
      self.data_manager.request_data('top10_holders', ts_code)  # ← 新增
  ```

- [ ] **Step 9: #9 板块概念（L1548-1553）**

  ```python
  # 在 except 中添加：
  except Exception:
      self.data_manager.request_data('concept', ts_code)  # ← 新增
  ```

- [ ] **Step 10: #10 多周期 K 线（L1657-1673）**

  ```python
  # 在 except 中添加：
  except Exception:
      self.data_manager.request_data('per_stock', symbol)  # ← 新增（注意这里是 symbol 不是 ts_code）
      continue
  ```

- [ ] **Step 11: #11 股东持仓（L704-748）**

  ```python
  # 在 except 中添加：
  except Exception:
      self.data_manager.request_data('top10_holders', symbol)  # ← 新增
      self.data_manager.request_data('stk_holder', symbol)      # ← 新增
  ```

- [ ] **Step 12: #12 因子缓存（L2419-2440）**

  ```python
  # 在 except 中添加：
  except Exception:
      self.data_manager.request_data('factor_precompute', ts_code)  # ← 新增
      registry_scores, registry_ok = self._compute_via_registry(df)
  ```

### Task 3: 验证

- [ ] **Step 1: 导入验证**

  ```bash
  PYTHONPATH=backend python -c "from app.services.signal_computation_service import SignalComputationService; print('Import OK')"
  ```

- [ ] **Step 2: 验证 daemon 端新 task_types 可导入**

  ```bash
  PYTHONPATH=backend python -c "
  from app.data.enhanced_cache_manager import EnhancedCacheManager
  ecm = EnhancedCacheManager()
  ecm.request_data('margin', '000001.SZ')
  ecm.request_data('concept', '000001.SZ')
  print('request_data OK')
  "
  ```

- [ ] **Step 3: Lint 检查（仅检查改动的两个文件）**

  ```bash
  PYTHONPATH=backend python -m ruff check \
    backend/app/services/signal_computation_service.py \
    backend/data_daemon.py
  ```

---

## 不纳入本次范围

- sync_requests 前端展示能力（daemon 队列消费者响应面板）
- daemon 新增 index_daily/news_sentiment/factor_precompute handler（日终同步已覆盖）
- 前端的空状态 UI 优化
- signal_computation_service.py 整体重构（P3 范围）
