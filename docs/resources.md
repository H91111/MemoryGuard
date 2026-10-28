# 开源资源、来源与自主边界

更新：2026-10-28。源码按 MIT 提供；第三方权重、运行库、字体和工具不随源码包分发。资源的实际执行以本次配置、原始响应及 manifest 为准。

| 资源 | 固定版本 / 来源 | 使用方式与许可 | 本次执行范围 |
|---|---|---|---|
| Python / SQLite | Python 3.12.14，SQLite 3.53.1；Python 标准库 | 存储、CLI、HTTP、模型请求；Python 原许可，SQLite 公共领域 | 核心与 day1 运行环境，无上游修改 |
| Qwen/Qwen3-0.6B-GGUF | Q8_0；revision `23749fefcc72300e3a2ad315e1317431b06b590a`；[官方文件](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/tree/23749fefcc72300e3a2ad315e1317431b06b590a) | 工具规划；Apache-2.0；固定权重，不训练，不分发 | day1 模型运行记录在 `output/evaluation-day1/`；以完成后的记录为准 |
| llama.cpp | `b11951` Windows CPU x64；[官方发布](https://github.com/ggml-org/llama.cpp/releases/tag/b11951) | 本地 chat-completions 服务；MIT；不修改上游 | 项目内 `runtime/llama-cpp/`，无需全局安装 |
| BAAI/bge-small-zh-v1.5 | revision `7999e1d3359715c523056ef9478215996d62a620`；[官方模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5) | 可选语义检索；MIT | day1 未运行；旧资源表的 CPU 推理与版本声明属于历史记录 |
| PyTorch / Transformers / NumPy 等 | 可选语义依赖见 `requirements-semantic.lock` | 仅供 BGE；遵守各组件 LICENSE/NOTICE | day1 核心和生成规划不依赖这些库；不把锁文件当安装或执行证据 |
| Ollama API | [官方接口](https://docs.ollama.com/api/chat) | 可选生成提取接口；所选权重许可另核对 | day1 未运行，不能与 Qwen 的规划实验混为一谈 |
| 自编合成数据 | `data/day1/`、`evaluation/build_day1.py` 与独立 `evaluation/labels/day1-*.jsonl` | 虚构 API、事件与评分；本工程 MIT | 开发者可见，自编合成，非真人数据或独立盲测 |
| ReportLab / pypdf / Poppler | 本次材料环境 ReportLab 4.4.9、pypdf 6.10.0；Poppler 负责渲染 | 报告制作与排版检查，不是产品依赖；分别保留原许可 | 报告输出与检查见 `output/pdf/` |
| FFmpeg / Windows 语音 | 本机 FFmpeg 8.1（构建启用 GPL）；系统 Huihui 中文语音 | 仅用于讲解视频；不分发二进制或语音引擎 | 视频为实际运行记录回放，含合成旁白，非真人录音 |

`scripts/setup_local_planner.py` 固定官方下载 URL，核对文件大小和上游 SHA-256，并在 `models/qwen3-0.6b/manifest.json`、`runtime/llama-cpp/manifest.json` 保存来源和本地文件哈希。模型文件为 639,446,688 字节，SHA-256 为 `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031`。运行 day1 时通过 `--model-manifest` 和 `--runtime-manifest` 将两份记录复制入配置并参与哈希；只提供服务别名不足以核验权重版本。

模型输出由真实推理产生；规则提取、范围隔离、重复证据合并、冲突与授权纠错、预算组织、可追溯恢复属于本工程实现。`impact.py` 仍使用确定性登录探针，不将其描述为模型完整能力预检。三组对照支持整套记忆策略在当前场景下的比较，没有单独隔离预检模块的贡献。

自主实现范围：事件协议与原文跨度校验、记忆治理、授权定向替代、SQLite 审计和分支回放、副本预检及提交、工作台、模型 HTTP 适配、统一预算、合成评测、原始记录与失败分析。不声称版本隔离、冲突记忆或外部记忆为首创。

参考项目 [SimpleMem](https://github.com/aiming-lab/SimpleMem)、[Graphiti](https://github.com/getzep/graphiti) 仅属于研究定位线索，未复用源码、未运行其原生对照。它们不等同于本工程的普通记忆基线。AI 开发参与见 [AI 辅助说明](ai-assistance.md)；团队的最终来源核查、参赛授权和成果归属需按实际情况确认。
