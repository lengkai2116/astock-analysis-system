---
title: 数据源变更远程诊断与GitHub分发升级方案
type: 架构设计
date: 2026-07-23
---

# 数据源变更远程诊断与GitHub分发升级方案

> **核心思路**：生产系统不自动修复数据源变更，而是通过系统管理模块导出诊断文件 → 开发端修订配置/代码 → 推送 GitHub → 生产系统拉取升级。形成"监控→诊断→修订→分发→升级"的闭环。

---

## 一、设计原则

| 原则 | 说明 |
|------|------|
| **生产只监测不修复** | 数据源适配器配置的修订由开发端完成，生产端只负责上报和接收更新 |
| **诊断文件自包含** | 一份 `.zip` 文件包含所有诊断信息，开发端可完整复现问题 |
| **GitHub 为分发中心** | 配置/代码的修订通过 GitHub Release 分发，生产系统校验后自动应用 |
| **用户可控升级** | 系统管理模块提供升级推送通知，用户确认后执行 |
| **离线兼容** | 诊断文件可手动拷贝传输，GitHub 不可用时走人工通道 |

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              生产环境 (用户设备)                               │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    系统管理模块 (前端页面)                               │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────┐  │   │
│  │  │ 数据源健康看板     │  │ 诊断导出中心      │  │ 系统升级管理          │  │   │
│  │  │ - 各源实时状态     │  │ - 手动导出诊断包   │  │ - 检查GitHub更新      │  │   │
│  │  │ - 历史质量趋势     │  │ - 自动生成报告    │  │ - 查看更新日志        │  │   │
│  │  │ - 异常告警记录     │  │ - 导出操作记录    │  │ - 确认/回滚升级       │  │   │
│  │  └─────────────────┘  └─────────────────┘  └──────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                              │                          ▲                   │
│              ┌───────────────┤                          │                   │
│              ▼               ▼                          │                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────┐      │
│  │ HealthScorer     │  │ DiagnosticExport  │  │ UpgradeManager      │      │
│  │ (实时评分引擎)    │→ │ (诊断包生成器)    │  │ (升级管理器)         │      │
│  └──────────────────┘  └──────────────────┘  └─────────┬───────────┘      │
│        │                      │                         │                  │
│        ▼                      ▼                         ▼                  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    data_daemon 数据采集进程                            │  │
│  │  东财Adapter  新浪Adapter  腾讯Adapter  (配置驱动: YAML)               │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
         │                        │                           │
         │ 诊断导出.zip            │ 查询更新                    │ 下载更新
         ▼                        ▼                           ▼
┌──────────────────┐    ┌─────────────────────────────────────────────┐
│ 用户手动传输       │    │          GitHub (开发端)                     │
│ (微信/邮件/网盘)   │    │                                             │
└──────────────────┘    │  ├─ config/data_sources/  (适配器配置)        │
                        │  ├─ backend/app/data/adapters/ (适配器代码)   │
                        │  ├─ tools/diagnostic_analyzer/ (诊断分析工具) │
                        │  └─ GitHub Release / Tags (版本分发)          │
                        └─────────────────────────────────────────────┘
                                  │
                                  │ Pull Request / 手动上传
                                  ▼
                        ┌─────────────────────┐
                        │  开发端诊断分析工具    │
                        │  diagnostic_analyzer │
                        │  - 解码诊断包         │
                        │  - 对比期望Schema     │
                        │  - 建议字段映射修正    │
                        │  - 生成新配置         │
                        └─────────────────────┘
```

---

## 三、核心组件设计

### 3.1 诊断文件格式 (Diagnostic Export)

诊断包是一个自包含的 `.zip` 文件，解压后结构如下：

```
diagnostic_20260723_153000.zip
├── manifest.json              # 元信息：系统版本、时间、触发原因
├── data_source_health.json    # 各数据源健康评分历史（最近500周期）
│
├── eastmoney/
│   ├── schema_expected.json   # 期望的字段Schema
│   ├── schema_actual.json     # 实际返回的字段Schema（最新采样）
│   ├── sample_response.json   # 3-5条原始API响应样本
│   ├── health_history.csv     # 最近500周期的健康评分明细
│   └── error_logs.txt         # 相关错误日志摘录
│
├── sina/
│   ├── schema_expected.json
│   ├── schema_actual.json
│   ├── sample_response.json
│   ├── health_history.csv
│   └── error_logs.txt
│
├── system_info.json           # Python版本、依赖版本、OS信息
├── adapter_configs/           # 当前生效的YAML配置文件副本
│   ├── eastmoney.yaml
│   ├── sina.yaml
│   └── tencent.yaml
└── summary_report.md          # 可读的问题摘要报告
```

#### manifest.json 示例

```json
{
  "diagnostic_version": "1.0",
  "created_at": "2026-07-23T15:30:00+08:00",
  "system_version": "2.1.0",
  "trigger": "manual",                // manual | auto_anomaly | scheduled
  "trigger_reason": "东财数据源持续3个周期健康评分<0.6",
  "data_sources": {
    "eastmoney": {"status": "degraded", "score": 0.35},
    "sina": {"status": "healthy", "score": 0.95},
    "tencent": {"status": "healthy", "score": 0.90}
  },
  "active_source": "sina",
  "total_cycles": 2873,
  "anomaly_started_at": "2026-07-22T09:30:00+08:00",
  "size_bytes": 28473
}
```

#### diagnostic_analyzer 用法（开发端工具）

```bash
# 开发端接收到诊断包后：
python tools/diagnostic_analyzer/analyze.py diagnostic_20260723_153000.zip

# 输出：
# ╔══════════════════════════════════════════════════╗
# ║            诊断分析报告                            ║
# ╠══════════════════════════════════════════════════╣
# ║ 系统版本: 2.1.0                                   ║
# ║ 异常时间: 2026-07-22 09:30                        ║
# ║                                                  ║
# ║ 问题: 东财API字段码变更                             ║
# ║ 检测到: f2 (期望price) 连续3周期空值率>90%          ║
# ║ 新增字段: f_newprice (疑似替代f2)                  ║
# ║                                                  ║
# ║ 建议修正:                                         ║
# ║   eastmoney.yaml field_mapping:                   ║
# ║     f_newprice → price  (替代原 f2)              ║
# ║                                                  ║
# ║ 生成补丁: patch_20260723_eastmoney_fix.zip        ║
# ╚══════════════════════════════════════════════════╝
```

### 3.2 系统升级管理器 (UpgradeManager)

生产系统通过系统管理模块自动接入 GitHub，拉取配置/代码更新。

```python
class UpgradeManager:
    """升级管理器——连接GitHub Release，验证并应用更新"""

    def __init__(self, github_repo: str, current_version: str):
        # github_repo = "username/astock-analysis-system"
        # current_version = "2.1.0"
        self._repo = github_repo
        self._version = current_version

    def check_update(self) -> Optional[ReleaseInfo]:
        """查询GitHub最新Release，返回可用更新信息"""
        url = f"https://api.github.com/repos/{self._repo}/releases/latest"
        # 不传token也可以查公开仓库
        resp = requests.get(url, timeout=10)
        latest = resp.json()
        # 比较版本号
        if self._is_newer(latest['tag_name'], self._version):
            return ReleaseInfo(
                version=latest['tag_name'],
                published_at=latest['published_at'],
                body=latest['body'],            # Release Notes
                download_url=latest['zipball_url'],
                checksum=latest.get('body', '')  # 内嵌SHA256
            )
        return None

    def download_update(self, release: ReleaseInfo, target_dir: str) -> bool:
        """下载更新包并校验完整性"""
        # 1. 下载zipball
        resp = requests.get(release.download_url, stream=True)
        sha256 = hashlib.sha256()
        with tempfile.NamedTemporaryFile(suffix='.zip') as tmp:
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)
                sha256.update(chunk)

            # 2. 校验SHA256（从Release body中提取）
            expected_sha = self._extract_checksum(release.checksum)
            if sha256.hexdigest() != expected_sha:
                logger.error("校验和不匹配，下载可能损坏")
                return False

            # 3. 解压到目标目录
            with zipfile.ZipFile(tmp.name) as zf:
                zf.extractall(target_dir)

        return True

    def apply_update(self, update_type: str, source_dir: str) -> bool:
        """应用更新

        Args:
            update_type: 'config' | 'code' | 'full'
            source_dir: 解压后的更新文件目录
        """
        if update_type == 'config':
            # 仅替换 config/data_sources/*.yaml
            shutil.copytree(
                f"{source_dir}/config/data_sources",
                self._config_dir,
                dirs_exist_ok=True
            )
            # ConfigWatcher 自动检测到文件变更
            logger.info("数据源配置已更新")

        elif update_type == 'code':
            # 替换 backend/app/data/adapters/*.py
            # 需要重启 data_daemon 使新代码生效
            shutil.copytree(
                f"{source_dir}/backend/app/data/adapters",
                self._adapters_dir,
                dirs_exist_ok=True
            )
            self._restart_daemon()

        return True

    def rollback(self, update_type: str) -> bool:
        """回滚到上一版本（保留最近3个版本的备份）"""
        backup_dir = f"{self._backup_root}/v{self._version - 1}"
        if os.path.exists(backup_dir):
            # 恢复备份
            shutil.copytree(backup_dir, self._config_dir, dirs_exist_ok=True)
            logger.info(f"已回滚至版本 {self._version - 1}")
            return True
        return False
```

### 3.3 系统管理模块前端界面

生产环境用户通过系统管理页面完成以下操作：

#### 数据源健康看板

```
┌─────────────────────────────────────────────────────────────┐
│  📊 数据源健康状态                              [导出诊断包]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  东财 HTTP API     ● 正常 (评分 0.98)      ↑ 稳定性 100%     │
│  新浪 HTTP API     ● 正常 (评分 0.95)      ↑ 稳定性 100%     │
│  腾讯 HTTP API     ◐ 降级 (评分 0.72)      ↓ 稳定性 95%      │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  健康评分趋势 (最近24小时)                            │   │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━       1.0 │   │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━          0.8 │   │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━                 0.6 │   │
│  │                                              ── 东财 │   │
│  │                                              ── 新浪 │   │
│  │                                              ── 腾讯 │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  [异常记录] 2026-07-22 09:30 东财price字段空值率>90%       │
│            09:31 自动切换至新浪  │  当前活动源: 新浪      │
└─────────────────────────────────────────────────────────────┘
```

#### 诊断导出中心

```
┌─────────────────────────────────────────────────────────────┐
│  📦 诊断导出                         上次导出: 未导出       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  导出范围:                                                   │
│  ○ 当前异常 (自动检测到的问题)                                │
│  ● 完整诊断 (所有数据源 + 配置 + 系统信息)                     │
│  ○ 指定时间段                                               │
│                                                             │
│  导出内容包括:                                               │
│  ✅ 各数据源健康评分历史 (500周期)                             │
│  ✅ API响应样本 (最近异常时段的3-5条)                          │
│  ✅ 当前适配器配置文件                                        │
│  ✅ 系统版本/依赖/日志摘录                                    │
│                                                             │
│  [导出诊断包] → diagnostic_20260723_153000.zip               │
│                                                             │
│  💡 提示：将导出的 .zip 文件发送给开发团队，                     │
│     以便远程分析问题并生成修复补丁。                            │
└─────────────────────────────────────────────────────────────┘
```

#### 系统升级管理

```
┌─────────────────────────────────────────────────────────────┐
│  🔄 系统升级                          当前版本: v2.1.0       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [检查更新]                                                  │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  发现新版本: v2.1.1                                    │  │
│  │  发布日期: 2026-07-23                                  │  │
│  │                                                       │  │
│  │  📝 更新内容:                                          │  │
│  │   - 修复: 东财API字段码变更(f2→f_newprice)              │  │
│  │   - 新增: 新浪五档盘口适配器优化                         │  │
│  │   - 优化: 并行采集线程数自动调节                         │  │
│  │                                                       │  │
│  │  更新类型: ● 配置更新 (无需重启)  ○ 代码更新 (需重启)     │  │
│  │                                                       │  │
│  │  校验码: a3f2b8c1d4e5...                              │  │
│  │                                                       │  │
│  │  [下载并应用]  [查看详情]  [忽略此版本]                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  更新历史                                                │  │
│  │  v2.1.0  2026-07-15  基础配置  ✅ 当前版本               │  │
│  │  v2.0.0  2026-07-01  初始版本   ✅ 已安装                │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、升级包规范

### 4.1 GitHub Release 结构

每次 Release 包含以下 artifacts：

```
Release v2.1.1
├── config-update.zip          # 仅配置更新 (~5KB)
│   ├── config/data_sources/eastmoney.yaml
│   ├── config/data_sources/sina.yaml
│   ├── CHANGELOG.md
│   └── checksum.sha256
│
├── code-update.zip            # 代码更新 (~50KB)
│   ├── backend/app/data/adapters/eastmoney.py
│   ├── backend/app/data/adapters/sina.py
│   ├── backend/app/data/adapters/base.py
│   ├── backend/app/data/adapter_manager.py
│   ├── backend/app/data/health_scorer.py
│   ├── CHANGELOG.md
│   └── checksum.sha256
│
└── full-update.zip            # 全量更新 (~10MB)
    └── (完整项目代码)
```

### 4.2 Release Notes 规范

GitHub Release body 包含结构化信息，供生产系统解析：

```markdown
## v2.1.1 (2026-07-23)

### 变更类型
Type: config, code          # config | code | full

### 兼容性
MinSystemVersion: 2.0.0     # 最低兼容系统版本
RequiresRestart: false       # config更新通常不需要重启

### 摘要
修复东财API字段码变更，优化新浪五档盘口数据获取

### 详细变更
- [config] eastmoney.yaml: f_newprice → price 映射
- [code] sina.py: 五档字段解析逻辑优化
- [code] base.py: 新增 retry_with_backoff 装饰器

### 校验码
ConfigSHA256: a3f2b8c1d4e5...
CodeSHA256: f6e7d8c9b0a1...
```

---

## 五、运维场景推演

### 场景1：东财字段码变更（标准流程）

```
时间线:

09:30  HealthScorer 检测到东财 price 字段空值率>90%，评分0.35
09:31  DataSourceManager 自动切换至新浪（业务无感）
09:31  系统管理模块记录异常，生成告警通知
       ─── 用户操作 ───
09:35  用户打开系统管理页面 → 看到"东财异常，已切换至新浪"
09:36  用户点击"导出诊断包" → 生成 diagnostic_20260723_0935.zip
09:37  用户将 .zip 发送给开发团队（微信/邮件）
       ─── 开发端操作 ───
09:40  开发端运行 diagnostic_analyzer
      → 自动识别出 f_newprice 字段疑似替代 f2
      → 生成 patch: eastmoney.yaml field_mapping 修正
09:45  开发端提交 PR，合并到 main 分支
09:46  创建 GitHub Release v2.1.1
      ─── 用户操作 ───
09:50  用户在系统管理页面点击"检查更新"
      → 发现 v2.1.1 (配置更新)
      → 查看更新日志 → 确认
09:51  系统下载 config-update.zip，校验SHA256
09:51  ConfigWatcher 检测到文件变更 → 热加载新配置
09:52  下一采集周期 → 东财恢复正常，评分升至0.98
09:52  系统自动切回东财为主源
```

**全程耗时：22分钟**（从用户发现到自动修复，实际人工操作约5分钟）。

### 场景2：配置更新不需要重启

```
升级包类型 = config
↓
UpgradeManager 替换 config/data_sources/*.yaml
↓
ConfigWatcher 1秒内感知文件变更
↓
DataSourceManager 热加载新配置
↓
下一采集周期自动生效
```

### 场景3：代码更新需要重启数据进程

```
升级包类型 = code
↓
UpgradeManager 替换 backend/app/data/adapters/*.py
↓
提示用户："数据源适配器已更新，需要重启数据后台进程？"
↓
用户确认 → 重启 data_daemon（launchctl restart）
↓
新适配器代码生效
```

### 场景4：用户无GitHub网络（纯离线）

```
生产系统无法访问 api.github.com
↓
系统管理页面显示"无法连接更新服务器"
↓
用户仍可手动导出诊断包
↓
开发端分析后，将修复补丁通过微信/邮件发送给用户
↓
用户手动下载补丁.zip，在系统管理页面选择"手动安装升级包"
↓
系统校验SHA256后应用
```

---

## 六、与 290 号方案的关系

| 维度 | 290号方案 (降级处理) | 291号方案 (本方案) |
|------|-------------------|------------------|
| **核心理念** | 系统自动适配数据源变更 | 系统监测并导出诊断 → 开发端修订 → GitHub分发 |
| **变更应对速度** | 即时（next cycle） | 22分钟（用户→开发→Release→更新） |
| **适用场景** | 字段值波动、网络抖动、临时故障 | 字段码变更、端点变更、协议变更 |
| **适用阶段** | 同一API版本内的波动 | API非兼容变更 |
| **是否需开发端介入** | 否（全自动） | 是（但开发端有分析工具辅助） |
| **是否需要GitHub访问** | 否 | 是（离线时有手动通道） |

**两者是互补关系**：
- 290号方案处理**轻微异常**（自动降级、自动恢复）
- 291号方案处理**结构性变更**（诊断+人工修订+分发升级）
- 290号的HealthScorer是291号DiagnosticExport的数据来源

---

## 七、实施计划

| 阶段 | 内容 | 预估 |
|------|------|------|
| **Phase 1** | HealthScorer 持续集成到 data_daemon | 1天 |
| **Phase 2** | DiagnosticExport 诊断包生成 + 系统管理页"数据源健康看板" | 2天 |
| **Phase 3** | UpgradeManager + GitHub Release 查询/下载/校验 | 1.5天 |
| **Phase 4** | 系统管理页"升级管理"前端界面 | 1.5天 |
| **Phase 5** | diagnostic_analyzer 开发端工具 | 1天 |
| **Phase 6** | 离线通道（手动安装补丁） | 0.5天 |
| **总计** | | **~7.5天** |
