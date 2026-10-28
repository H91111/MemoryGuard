# Day-one 同模型比较协议

本评测与 `synthetic-regression-v2` 及 `output/evaluation-v020/` 分开。数据由程序自编，开发者可见；2 条 dev 与 6 条 acceptance 采用不同项目名和任务 ID，仍共享构造骨架，不是独立盲测或真实用户验证。软件修正后重跑仍作为探索验证。

每流 4 个检查点：学习 v1、正常学习 v2、v1 同属性重复干扰加 v2 冲突、授权纠错。每个检查点 3 个探针：答案持续有效的 v1 旧任务、v2 新任务、缺知识的 v9 边界任务。acceptance 默认三方法共 6×4×3=216 次 planner 执行，不等于独立问题数。初始 v2 与冲突检查点的 v2 均应澄清。

比较 `no_memory`、`latest`、`governed`。三组调用相同 callable、提示词模板和生成参数；每方法每流重置记忆，单次规划无会话状态，无工具结果回写。latest 按相同项目、版本、所需属性过滤原样观察，最近优先。governed 采用现有规则治理和字符检索，重复合并、冲突前置检测、授权纠错。三者收到相同任务元数据，latest 同样看到证据来源。原始来源不是事实正确性标签。

共享 ChatPlanner 适配器保留记忆可用性门控：已知缺少必要属性、未决冲突或不支持的操作/范围，将 JSON schema 约束为 clarify，模型生成澄清文本；证据充分时，模型选择是否调用及具体参数。门控使用 task/context，不使用评分答案。服务越过门控、输出格式错误或引用不存在的证据均记录为 error。此设置比较的是“共享门控与模型规划 + 不同记忆策略”，不将缺证/冲突时的澄清决策归因于模型独立识别。

事实统一投影为 fact_id、project、version_scope、attribute、value、created_step、单份代表 evidence 和 evidence_count。全组预算均为 canonical JSON facts 数组的 UTF-8 字节数（默认 2048），top-k 默认 8；任务、共享系统提示词和上下文状态字段在该证据预算外。真实模型 token 用量由 planner trace 单独记录，字节代理不称为 tokenizer 精确 token 数。latest 保留每次重复观察，治理保留一个逻辑事实和证据计数，这正是待比较的上下文策略差异。

评分文件与任务流分开；planner 仅接收 task/context。评分规格在 planner 返回之后交给独立 `mock_api_call`，不向规划器传答案或模拟器反馈。探针前后状态哈希必须一致。记录每次输入、预测、执行结果、标签答案哈希；模型原始请求响应由 callable 返回的 model_trace 保存。异常记录为 error，不回退成确定性成功。

指标按 count/total/rate 保存：可回答任务成功率、新任务成功率、旧任务退化率、错误调用/全部执行、错误调用/实际调用、多余澄清/可回答任务、正确澄清/不可回答任务。旧任务只比较同 task_key 的相邻检查点，要求前后均可回答、去掉管理字段 task_id 后的公开任务哈希相同、评分答案哈希相同且前次成功；分母 0 时 rate=null。冲突时的合理澄清不算旧任务退化。保留每个有效配对以核验分母。

该实验比较整套记忆策略；不单独宣称预检模块增益。`impact.py` 当前仍以确定性规划器预检，不能将这里的真实模型任务执行表述为真实模型预检。版本隔离本身通常让 latest 和 governed 都保留 v1；重复观察挤出另一必需属性才形成仍有效旧任务的干扰。模型可能凭空猜中或拒答，应保留实际结果，不预设治理优势。

运行前冻结配置、输入和评分哈希，输出复制任务流及独立评分文件；每次调用后追加并 flush `raw.jsonl` 和 `progress.json`。输出目录必须不存在，拒绝覆盖历史。完整结束才写 summary.json。输入生成：`python -m evaluation.build_day1`。确定性流程验证：`python -m evaluation.day1 --deterministic-smoke --split dev --out output/day1-smoke-unique`，此命令不能作为 AI 实测证据。真实模型通过 `evaluate(planner, out, split='acceptance', planner_config=...)` 接入。

CLI 可显式传 `--model-manifest models/qwen3-0.6b/manifest.json --runtime-manifest runtime/llama-cpp/manifest.json`。JSON 内容在运行开始前快照进入 config.json 的 planner.model_artifact/runtime_artifact，并参与 config_hash；路径缺失或 JSON 无效则不开始运行。不传时只记录服务别名及配置，不推断服务端使用了本地文件或特定运行时。
