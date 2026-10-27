# Memory Guard · 持续学习负影响防护

**v0.2.0 本地交付版 · 2026-10-26**

面向 Lifelong Learning Agent 的外部记忆治理：学习前试写与对照旧任务，学习后检查冲突、行为变化和能力保留，并支持证据审计与历史恢复。

## 立即使用

需要 **Python 3.11+**。离线核心零第三方依赖，无需 GPU、账号或 API key。

1. 解压压缩包到可写目录。
2. 双击 **启动工作台.cmd**。
3. 浏览器打开 `http://127.0.0.1:8765`。保留启动窗口；Ctrl+C 停止。

首次载入完整演示，也可新建空白会话。端口占用时：

```powershell
powershell -File start.ps1 -Port 8766
```

完整操作步骤见 [使用说明](docs/product-guide.md)。

## 这版做了什么

- **学习前预检**：在独立副本试写，比较旧任务的调用参数和可用性；正式记忆不改变。
- **确认后提交**：冲突、参数变化、待复核内容需要查看影响后确认；旧预检不能覆盖已经更新的记忆。
- **负影响监测**：展示逐步学习中的调用保持、阻断、参数变化和恢复，能展开前后证据。
- **恢复与备份**：会话持久切换，检查点分支恢复，审计 JSON 导入导出，损坏包不会替换当前数据。
- **自定义工作区**：填写自己的项目/版本，支持有效日期，生成有证据的调用计划。
- **工程修复**：Python 3.11 启动兼容、重复证据不再挤占必要任务上下文、空白会话重启保留、来源/输入错误提示。

原有项目/版本隔离、重复证据关联、定向纠错、CLI、可选 BGE/Ollama 接口继续保留。

## LLA 与负影响如何结合

```text
新事件 → 原文与范围校验 → 私有副本试写 → 固定旧任务前后对照
                                      ↓
                   保留 / 阻断 / 参数变化 / 恢复 / 无基线
                                      ↓
                     查看影响 → 确认追加 → 审计与历史分支
```

工作台比较的是**行为变化**。参数改变可能是正确适应，冲突导致澄清可能是正确防护，均不能直接叫作灾难性遗忘。评测另用独立模拟器判断任务成败，并同时呈现多余澄清，避免“全部拒答”看起来最好。

当前 LLA 指固定权重下的非参数外部记忆适应；默认提取器和规划器为确定性程序，不冒充生成模型或模型持续训练。

## Python 接入

```python
from memory_guard import MemoryGuard
from memory_guard.impact import prepare, commit

memory = MemoryGuard('runtime/my-agent.db')
proposal = prepare(memory, {
    'event_id': 'docs-001', 'source_id': 'team-docs',
    'project': 'Orion', 'version_scope': 'v1',
    'text': '登录路径为 /login；认证字段为 api_key。',
})
print(proposal.report)  # 不改变正式记忆
if not proposal.report['requires_acknowledgement']:
    commit(memory, proposal)
# 有影响时，将 report 呈现给使用者；确认后才 acknowledge=True。
memory.close()
```

运行 `python -m examples.lifelong_agent` 查看完整学习门控示例。直接 `ingest` 为兼容 API，不强制预检；需要强制门控的宿主只暴露 prepare/commit。导入的来源策略须与本地配置一致。

## CLI 与验收

在解压后的项目根目录执行：

```powershell
python -m memory_guard --db runtime/demo.db demo
python -m memory_guard --db runtime/demo.db preview data/examples/new_event.json
python -m memory_guard --db runtime/demo.db impact
python -m memory_guard --db runtime/demo.db fork runtime/branch.db --checkpoint 4
python -m memory_guard --db runtime/demo.db query --project Atlas --version v2
python -m unittest discover -s tests -v
python -m memory_guard evaluate --out output/evaluation-v020
```

评测数据保持原包的8条固定合成测试流。本轮离线执行 B0/B2/B3 三种方法，共480次探针执行（432次常规、48次配对诊断），不是480个独立问题。更新动作匹配96/96；详细计数、输入哈希和原始执行见 [本轮评测](output/evaluation-v020/summary.json)。

| 方法 | 可回答任务成功 | 冲突/不可回答时强答 | 多余澄清 | 旧任务成功 |
|---|---:|---:|---:|---:|
| 无跨任务记忆 B0 | 0/88 | 0/56 | 88/88 | 0/48 |
| 同范围最近优先 B2 | 70/88 | 8/56 | 18/88 | 48/48 |
| 规则治理 + 字符检索 B3 | 88/88 | 0/56 | 0/88 | 48/48 |

这是工程回归结果。样例由开发者编写且可见，不代表独立盲测，不证明通用智能体收益；本次未重跑神经检索或生成模型实验。原包历史资料在本地交付目录的 `legacy-v010/`，不作为新版验收，精简 ZIP 不重复收录旧媒体。

## 可选模型

离线体验不需要以下步骤。语义检索沿用原包固定的 `BAAI/bge-small-zh-v1.5@7999e1d3359715c523056ef9478215996d62a620`：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-semantic.lock
.\.venv\Scripts\python.exe -m scripts.download_model
.\.venv\Scripts\python.exe -m memory_guard --db runtime/demo.db query --project Atlas --version v2 --mode hybrid
```

模型不可用时明确报错。Ollama 提取使用 `--extractor ollama ingest`，具体见 [API 与可选模型](docs/api.md)。本轮验证了故障降级，未下载/运行生成模型。

## 交付内容

| 路径 | 内容 |
|---|---|
| `memory_guard/` | SQLite 核心、预检与提交、会话管理、本地 HTTP 工作台 |
| `examples/lifelong_agent.py` | 学习门控接入示例 |
| `tests/` | 核心、影响、会话与 HTTP 自动验收 |
| `evaluation/`、`data/` | 合成场景、独立评分、负影响指标 |
| `output/evaluation-v020/` | 本轮配置、原始执行与结果 |
| `output/acceptance/` | 本轮验收日志 |
| `docs/product-guide.md` | 产品使用说明与五分钟演示 |
| `docs/release-notes.md` | 变更与边界 |
| `manifest.json` | 发布文件 SHA-256 清单 |

单进程本机应用，服务仅绑定127.0.0.1；无多用户认证或公网部署支持。原文校验与范围规则不能保证复杂自然语言语义正确。自定义项目没有独立工具规格时只生成计划，不调用真实业务 API。

源码沿用 [MIT](LICENSE)；第三方模型和依赖遵守各自许可，见 [NOTICE](NOTICE)。
