# Phase 1 — 第五梯队：事件监控 + L4诊断 + 引擎标签化

> **基准文件**：303号§三，300号，302号

**执行顺序**：
1. **并行启动**：P2.1（事件监控）+ P2.5（引擎标签化）— 两者独立
2. **串行等待**：P2.2（L4仲裁）→ 需要 P2.1 的事件综合评分

### Task 1: P2.1 事件监控器 (2周)
- Create: `backend/app/opportunity_atlas/event_monitor.py`
- EventMonitor 类：20类事件检测 + 双通道 + 评分合并 + 新闻质量过滤

### Task 2: P2.5 引擎标签化 (2周, 9项子任务并行)
- Modify: volume_price_strategy.py, chanlun_strategy.py, chip_strategy.py, chip_distribution_service.py, chip_pre_filter.py
- Create: `backend/app/opportunity_atlas/time_rhythm_engine.py`

### Task 3: P2.2 L4共识投票引擎 (1周, P2.1完成后)
- Create: `backend/app/opportunity_atlas/cross_validate.py`
