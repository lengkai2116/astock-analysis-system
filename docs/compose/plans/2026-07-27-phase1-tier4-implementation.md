# Phase 1 — 第四梯队：标签池接口 + Treemap API + 标的库 CRUD + 预设场景

> **基准文件**：303号§三，294号§五

**目标**：4 项任务并行推进，使 Treemap 前端接入真实数据。

### P1.1 统一标签池查询接口 (0.5周)
- Modify: `backend/app/data/enhanced_cache_manager.py` — 新增 query_tags 方法
- 按 tag_name + tag_value 组合查询，AND 逻辑

### P1.4 Treemap 后端 API (0.5周)  
- Create: `backend/app/routes/opportunity_atlas.py` — 新 Blueprint
- `/api/v3/opportunity-atlas/treemap?mode=market|opportunity|value`

### P1.2 标的库 CRUD (1周)
- Modify: `backend/app/models/opportunity_library.py` — 新建模型
- Create: `backend/app/routes/opportunity_library.py` — CRUD 路由

### P1.5 预设场景前端 (0.5周)
- Modify: `_ui-prototype/opportunity-treemap.html` — 预设按钮
