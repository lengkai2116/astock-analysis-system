# 条件说明生成模块

## 用途

为股市监控通知管理系统的 **~100条条件** 批量生成用户友好的自然语言说明。

## 工作流程

```
编写 conditions_input.json                            [手动，约1小时]
      │
      ▼
bash run_generation.sh                                [自动，约15-30分钟]
      │
      ├─ 检查 LM Studio 服务状态
      ├─ 逐条调用 Qwen3.5-9B / DeepSeek V4 生成说明
      ├─ 每5条自动保存检查点（断点续传）
      └─ 全部完成后输出 output/condition_descriptions.json
      │
      ▼
bash run_validation.sh                                 [自动，数秒]
      │
      ▼
人工审核修正                                            [0.5-1天]
```

## 前置要求

**方式 A：LM Studio + Qwen3.5-9B（推荐，本地免费）**
1. 打开 LM Studio → 加载 Qwen3.5-9B-Q6_K.gguf
2. 点击 "Start Server" 启动 API 服务器
3. 确认 API 地址（默认 http://192.168.3.1:1234）

**方式 B：DeepSeek V4（需网络 + API Key）**
1. 设置环境变量 DEEPSEEK_API_KEY
2. 系统会自动使用 DeepSeek V4

## 使用方法

### 方式 A：Web UI（推荐）

启动独立 Web 服务器，通过浏览器操作：

```bash
# 启动 UI 服务器（默认端口 8765）
python3 ui_server.py

# 自定义端口
python3 ui_server.py --port 8888

# 启动后自动打开浏览器
python3 ui_server.py --open
```

打开浏览器访问 `http://localhost:8765`，界面功能：

| 区域 | 功能 |
|:-----|:------|
| 🎮 控制面板 | 选择引擎 → 点击「开始生成」→ 进度条实时显示 |
| 📋 日志 | 实时输出生成过程，每条的完成状态 |
| 📦 条件清单 | 查看所有待生成的条件，已完成的自动标注 ✅ |
| ✅ 结果 | 生成完成后预览每条条件的说明 + 📥下载 JSON |

### 方式 B：命令行

```bash
# 一键生成
bash run_generation.sh

# 验证质量
bash run_validation.sh

# 查看日志
cat output/_generation_log.txt
```

## 断点续传

脚本每 5 条自动保存 `output/_checkpoint.json`，
中断后重新运行会自动跳过已生成的。

## 输出说明

输出文件 `output/condition_descriptions.json` 结构：

```json
{
  "condition_id_1": {
    "user_description": "一句话解释",
    "how_it_works": "逻辑说明",
    "parameter_descriptions": {"参数名": "说明"},
    "when_to_use": "适用场景",
    "when_not_to_use": "失效场景",
    "example": "真实案例",
    "related_conditions": [
      {"condition_id": "...", "reason": "关联原因"}
    ]
  },
  ...
}
```

## 质量保证

- **先跑试验**：先在 conditions_input.json 中挑 3 条差异大的条件运行
  - 一条价格类（如 `price_above`）
  - 一条技术指标类（如 `macd_jincha`）
  - 一条策略信号类（如 `chanlun_diyi_maidian`）
- **确认质量**后删除 output 目录，全量生成~100条
- **人工审核**修正细节（约0.5天）

## 后续维护

新增条件时：
1. 在 conditions_input.json 中添加新条件
2. 重新运行生成脚本
3. 新条件会追加到 output/condition_descriptions.json

## 与后端集成

生成完成后，可将 output/condition_descriptions.json 导入后端：

```bash
# 将说明导入 condition_registry 表的 description 字段
python3 scripts/import_to_db.py
```

详情见 206号方案 §4.5。
