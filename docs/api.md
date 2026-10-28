# API 与数据合同

## 库

`MemoryGuard(path=":memory:", stream_id="default", trusted_sources=("maintainer",), extractor=None, encoder=None)`：一个库对应一条事件流。不同stream/source/rule策略不能复用同一库。

- `ingest(event)`：原文先归档；验证候选并生成决策。候选无效保存pending；事件结构无效整体拒绝。外部extractor异常回滚，不留下半写入。
- `correct(target_id, event)`：复用ingest，强制kind=correction与目标。授权、范围及有效区间不符时pending；不能替代已被替代目标或建立自我替代。
- `retrieve(query, scope, checkpoint=None, token_budget=2048, top_k=8, mode="character")`：scope含project/version_scope，可含subject、attributes、as_of；mode支持character/semantic/hybrid。先检查全部适用事实的冲突，再应用排序和预算。
- `inspect(fact_id, checkpoint=None)`：事实、原文跨度、来源、关系和决策链。
- `snapshot()`：带流前缀内容校验的cp标识；也可用整数检查点0..最新步。
- `state(checkpoint=None)`：只读导出已观察前缀和状态哈希。
- `export()` / `MemoryGuard.replay(exported, path)`：保存原文及当时提取结果，不重新调用不稳定模型；重建后检查全部状态摘要。回放目标须为空库。

事件必填event_id/text/source_id；建议显式project/version_scope/observed_at。kind默认observation。授权纠错需kind=correction、target_id、可信source_id。结构化候选需confirmed=true；候选值必须逐字出现在指定原文跨度中。`valid_from/valid_to`为ISO8601，可为空。不把observed_at当有效时间。原文最多16000字符，不自动截断。

## 本机 HTTP

仅监听127.0.0.1。所有POST须`Content-Type: application/json`及`X-Memory-Guard: local`；浏览器Origin须与本机端口一致。没有CORS通配或远程认证。

| 方法/路径 | 行为 |
|---|---|
| GET `/api/state?checkpoint=5` | 指定前缀的记忆、决策、来源与统计 |
| GET `/api/export` | 下载可回放JSON审计包 |
| GET `/api/evaluation` | 读取本地已生成的summary.json |
| POST `/api/ingest` | 写入事件对象 |
| POST `/api/correct` | `{target_id,event}`定向纠错 |
| POST `/api/task` | `{task,checkpoint,mode,token_budget}`生成调用并运行模拟器 |
| POST `/api/demo-step` | `{index:0..5}`六步演示事件 |
| POST `/api/new-session` | 创建新库，保留旧库 |

网页模拟器只预置Atlas v1/v2与Beacon v2。自定义项目的调用计划仍可生成，但模拟执行需要另行配置独立规格。模拟器在规划后执行，其完整规格从未传给规划器。源码与评测同进程的逻辑边界不等同OS安全沙箱。

## v0.2.0 学习门控

`memory_guard.impact`：

- `prepare(guard, event, tasks=None)`：冻结提取结果，在副本试写；返回 PreparedUpdate，公开展示 `.report`。tasks为空时自动覆盖已有范围的登录任务，也可传包含 as_of/required 的固定任务数组。
- `commit(guard, prepared, acknowledge=False)`：校验预检完整性与原状态哈希；有影响需 acknowledge=True；使用已冻结候选追加，不重新提取。
- `compare(before, after, tasks=None)`：两个独立 MemoryGuard 状态的只读行为比较。
- `fork(guard, checkpoint=None, path=':memory:')`：创建经过摘要核验的独立历史分支。
- `history(guard, checkpoint=None)`：按每个事件前缀比较前后，历史探针不读取未来事实。

| 方法/路径 | 输入与结果 |
|---|---|
| GET `/api/health` | 产品名、版本、工作区路径摘要 |
| GET `/api/sessions` | 当前会话ID与可恢复会话列表 |
| GET `/api/impact?checkpoint=5` | 截至检查点的逐步任务影响 |
| POST `/api/preview` | `{event}`；返回 `preview_id` 与行为对照，不写入 |
| POST `/api/commit` | `{preview_id,acknowledge}`；令牌15分钟有效、单次使用，状态变化后拒绝 |
| POST `/api/new-session` | `{name,demo:false}`；新建并切换，demo=true载入完整演示 |
| POST `/api/switch-session` | `{session_id}`；只接受已注册会话ID |
| POST `/api/restore` | `{checkpoint:4,name}`；原始会话保留，创建独立前缀分支 |
| POST `/api/import` | `{audit,name}`；审计包验证成功后切换新会话 |

输入错误返回400 JSON，Host/Origin/请求头失败返回403；未匹配路由404。一般POST体100KB以内，导入体10MB以内。预检最多缓存32条，切换会话清空令牌。网页自定义写入走预检；兼容的 ingest/correct 与演示重放直接写入，宿主如需强制预检须隐藏这些入口。

检索结果携带一份代表 evidence 和完整证据数量 evidence_count；inspect/state/export 仍保留全部原文。`token_budget`沿用原参数名，实际单位为 UTF-8 字节代理，不是生成模型实测token。

## 可选 Ollama 提取

在本地另行安装并启动模型后：

```powershell
$env:MEMORY_GUARD_MODEL = 'qwen2.5:3b'
$env:MEMORY_GUARD_OLLAMA = 'http://127.0.0.1:11434'
python -m memory_guard --extractor ollama --db runtime/model.db ingest data/examples/new_event.json
```

候选须通过原文跨度和值检查；失败进入待复核。模型不能授予纠错权限。v0.2.0 只验证此提取接口失败路径；day1 未运行 Ollama 提取。网页固定规则提取；Python prepare 支持传入使用 OllamaExtractor 的 MemoryGuard。

## day1 可选真实模型工具规划

```python
from memory_guard.agent import run_agent
from memory_guard.llm import ChatPlanner

planner = ChatPlanner(model='qwen3-0.6b-q8_0', base_url='http://127.0.0.1:18080/v1')
result = run_agent(memory, {
    'project': 'Atlas', 'version_scope': 'v2',
    'query': '请使用第二版文档规定的登录 API。',
}, planner=planner)
```

`run_agent(..., planner=None)` 保持原确定性行为；`planner(task, context)` 可注入真实规划器。`ChatPlanner` 使用标准库请求 chat-completions，固定 temperature=0、seed=42、max_tokens=384，关闭 thinking，并使用 JSON schema 限制输出结构。已有缺证、冲突或不支持的范围将 schema 约束为 `clarify`，模型生成澄清文本；证据充分时由模型选择调用及参数。所有策略共用这一适配器，不重试、不用规则规划器修补参数。服务未遵守约束时返回 `error`。

`result.status` 为 `call`、`clarify` 或 `error`。`error` 表示网络、截断、JSON 或协议错误，不能当成正确澄清。`tool_args` 的范围、载荷和引用格式经过校验；路径、认证字段是否正确由独立模拟器评分。SDK 的返回值含 `model_trace`（请求、原始响应与错误）和实际 `token_usage`；这些是运行记录，调用者应自行决定保存位置。

`python -m memory_guard ... query --planner llm` 提供 CLI 入口，`--model` 和 `--base-url` 可选择兼容服务。项目内本地服务通过 `python -m scripts.setup_local_planner --start` 设置，不改系统脚本执行策略。`runtime/llama-cpp/server.json` 记录 PID 和启动参数；用 `Stop-Process -Id <PID>` 停止对应服务。

`examples.llm_agent` 演示真实模型规划、确定性预检、脚本确认写入、冲突澄清与历史分支，独立输出原始记录。脚本中的 acknowledge=True 是预设演示行为，不表示人工审核。网页和影响预检尚未注入此模型；不要把 day1 的策略对照称为模型预检消融实验。
