# Phase 1 — 第六梯队：操作建议 + 通知/雷达/看板

> **基准文件**：303号§三（唯一基准），299号§四/§五/§七/§八

**目标**：完成最后2项工序，使标的库自动产出操作建议 + 通知推送 + 机会雷达 + 自选看板

### P2.3 操作建议生成 (1周)
- Create: `backend/app/opportunity_atlas/advice_generator.py`
- P1.2标的库 + P2.2 L4诊断 → operation_advice 写入

### P2.4 通知/机会雷达/看板接口 (1周)
- Create: `backend/app/opportunity_atlas/radar_service.py`
- 机会雷达：非自选股关键信号轮播
- 看板接口：自选看板后端
- 通知推送分级（紧急/重要/常规）
