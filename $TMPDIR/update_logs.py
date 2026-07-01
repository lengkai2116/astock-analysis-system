#!/usr/bin/env python3
import sys

filepath = "/Users/kalence/Desktop/01-A股股票分析系统/001-沟通记录/30-06-30沟通纪要.md"

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old_text = "⑥ playback   ✅ #221 ← 刚完成\n⑦ strategy-sandbox ← 下一个\n⑧ ai-analysis ✅ #217\n⑨ factor-manager ✅ #219\n⑩ strategy-templates ✅ #220\n⑪ reports-center\n⑫ alert\n⑬ system-management\n⑭ account\n```"

new_text = "⑥ playback   ✅ #221\n⑦ strategy-sandbox ✅ #222 ← 刚完成\n⑧ ai-analysis ✅ #217\n⑨ factor-manager ✅ #219\n⑩ strategy-templates ✅ #220\n⑪ reports-center ← 下一个\n⑫ alert\n⑬ system-management\n⑭ account\n```\n\n## 012 — 策略沙箱核对审计+后端技术规格书\n\n**沟通主题：** 全量核对策略沙箱原型 vs 166号/171号文档一致性，产出后端开发技术规格书 #222\n\n### 审计发现\n\n- **~95% Mock：** 14大类全部为客户端生成数据，0后端API调用\n  - 8个策略radio硬编码（S1-S5 + F1-F3），不连接策略模板/因子管理\n  - 8只自选股硬编码WATCHLIST_STOCKS数组\n  - 8项指标固定Mock值（+24.3%/+11.2%等）\n  - 权益曲线Math.random()生成（29个月无真实历史数据）\n  - 行情分段看固定文案（+18.5%/-5.2%/+2.1%）\n  - 参数稳定度Math.random()带偏倚\n  - 信号明细10行硬编码\n  - 结论固定模板拼接（与计算结果无关）\n\n### 后端就绪审计\n\n- ✅ 已实现：sandbox.py（signal-records查询）+ indicator_sandbox.py（通用代码执行沙箱，与策略沙箱不同概念）\n- ❌ 待建：POST /api/v3/sandbox/run（核心端点，全量待实现）\n- **后端就绪度：~20%**（信号列表接口可用但原型未使用，核心计算端点全量待建）\n\n### 关键差异\n\n- **D1-D3/D8均为P0：** 策略选择硬编码、自选股硬编码、全量计算结果Mock、策略引擎服务层缺失\n- **D5-D7为P1：** \"纳入回测\"仅alert占位、参数调节不参与计算、与backtest页概念不一致\n\n### 开发计划\n\n- **Phase 1（~3天）：** POST /api/v3/sandbox/run核心端点 + SandboxService + 信号生成/净值计算/指标聚合/行情段分类\n- **Phase 2（~2天）：** 参数稳定度测试 + 策略源同步 + 参数接入 + 纳入回测 + 结论规则推理引擎\n\n### 产出文件\n- `002-方案存档/222-策略沙箱后端开发技术规格书.md`（9章+2附录，完整端点到前端适配清单）\n\n### 审计队列进度\n```\n① dashboard  ✅ #213   ② screener   ✅ #214\n③ indicator-ide ✅ #215 ④ watchlist  ✅ #216\n⑤ backtest   ✅ #218   ⑥ playback   ✅ #221\n⑦ strategy-sandbox ✅ #222 ← 刚完成\n⑧ ai-analysis ✅ #217  ⑨ factor-manager ✅ #219\n⑩ strategy-templates ✅ #220\n⑪ reports-center ← 下一个\n⑫ alert  ⑬ system-management  ⑭ account\n```"

if old_text in content:
    content = content.replace(old_text, new_text)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print("SUCCESS")
    sys.exit(0)
else:
    print("NOT FOUND")
    # Debug: show the exact chars around that position
    idx = content.find("playback   ✅ #221")
    if idx >= 0:
        print("Found context at", idx)
        print(repr(content[idx:idx+200]))
    sys.exit(1)
