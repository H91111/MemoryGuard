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

这是 v0.2.0 的确定性工程回归结果。样例由开发者编写且可见，不代表独立盲测，不证明通用智能体收益；这组数字没有生成模型参与。day1 的真实模型实验使用独立数据及输出目录，见下文。

## day1 真实模型规划

工具规划支持固定权重的 Qwen3-0.6B Q8_0，通过项目内 llama.cpp CPU 服务生成结构化调用或澄清。核心库仍无第三方运行依赖；首次设置会从官方来源下载约 640MB 权重及 Windows 推理程序，不进入源码包。

```powershell
python -m scripts.setup_local_planner --start
python -m memory_guard --db runtime/demo.db demo
python -m memory_guard --db runtime/demo.db query --project Atlas --version v2 --planner llm
python -m examples.llm_agent --out output/day1-demo-new
python -m evaluation.day1 --split acceptance --out output/evaluation-day1-new --model-manifest models/qwen3-0.6b/manifest.json --runtime-manifest runtime/llama-cpp/manifest.json
```

输出目录必须为新目录。`ChatPlanner` 保存提示词、请求、原始响应、token 用量和错误；没有规则参数兜底。已知缺证、冲突或不支持的范围由共享记忆门控约束为澄清，证据充分时模型选择调用及参数。SDK 可用 `run_agent(memory, task, planner=ChatPlanner())`。模型只接收任务及记忆证据，评分答案在返回后进入本地模拟器。

新协议为 6 条流、每流 4 检查点和 3 个探针，三组共 216 次执行。三组使用同模型、同提示词和同一事实格式，以 2048 UTF-8 字节限制证据数组，状态/冲突等治理元数据在预算外。普通记忆也按项目、版本过滤。只在公开任务和有效评分答案不变、前次成功时统计旧任务退化。数据为开发者可见的自编合成场景，不是独立盲测。

网页及 `impact.prepare/compare` 仍使用确定性规划器；day1 模型结果不能证明真实模型的预检效果。协议详见 [day1 实验说明](evaluation/configs/day1.md)。

2026-10-28 已完成 216 次真实模型验收、56 项自动测试及 8 次模型演示调用。结果保留所有失败；数据是开发者可见的自编合成场景，以下执行不等于独立问题数。

| 方法 | 可回答成功 | 新任务成功 | 旧任务退化 | 模型协议错误 |
|---|---:|---:|---:|---:|
| 无跨任务记忆 | 0/36 | 0/12 | 不适用（0/0） | 0 |
| 同范围最近优先 | 21/36 | 11/12 | 5/10 | 3 |
| MemoryGuard | 32/36 | 10/12 | 1/17 | 4 |

治理组的新任务指标低于普通记忆，不能称为全面改善。旧任务分母也随各方法先前是否成功而异。详见 [原始汇总](output/evaluation-day1/summary.json)、[报告内容](docs/day1-report.md)、[初赛材料](docs/day1-submission.md) 和 [GitHub 状态](https://github.com/H91111/MemoryGuard/issues/1)。本地发布包通过 `python -m scripts.package_release --day1` 构建。

## 可选模型

离线体验不需要以下步骤。语义检索沿用原包固定的 `BAAI/bge-small-zh-v1.5@7999e1d3359715c523056ef9478215996d62a620`：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-semantic.lock
.\.venv\Scripts\python.exe -m scripts.download_model
.\.venv\Scripts\python.exe -m memory_guard --db runtime/demo.db query --project Atlas --version v2 --mode hybrid
```

模型不可用时明确报错。Ollama 提取使用 `--extractor ollama ingest`，具体见 [API 与可选模型](docs/api.md)。BGE/Ollama 是单独的可选提取/检索接口，其历史记录与 day1 的 Qwen 工具规划实验分别说明。

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
