> 此文件继承自 v0.1.0，描述第三方资源来源；历史环境与模型记录已移至 legacy-v010/。本轮未运行神经模型。

# 开源资源、来源与自主边界

本工程代码按MIT提供。第三方权重/运行库不随源码压缩包分发；安装时保留各自LICENSE/NOTICE。模型、代码和测试数据许可分别处理，不把模型卡许可扩展到其他项目。

| 资源 | 固定版本 / 来源 | 用途与许可记录 | 本工程修改 |
|---|---|---|---|
| Python / SQLite | 本机Python 3.12.10，标准库sqlite3 | 核心存储、CLI、HTTP服务；Python原许可，SQLite公共领域 | 不修改上游 |
| BAAI/bge-small-zh-v1.5 | revision 7999e1d3359715c523056ef9478215996d62a620；[官方模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5) | 中文候选/任务语义排序；模型卡MIT；本机真实CPU执行 | 不训练、不修改权重；固定CLS/归一化/查询指令 |
| PyTorch | 2.8.0+cpu；[官方](https://pytorch.org/) | BGE推理；本机发行包元数据BSD-3-Clause | 无 |
| Transformers | 4.57.1；[官方仓库](https://github.com/huggingface/transformers) | 模型/分词器加载；Apache-2.0 | 无 |
| NumPy | 2.5.3；[官方](https://numpy.org/) | 向量点积；本机发行元数据含BSD/MIT/Zlib等组件 | 无 |
| tokenizers / safetensors / huggingface-hub | 0.22.2 / 0.8.0 / 0.36.2 | 分词、权重、获取依赖；Apache相关许可，见原始发行文件 | 无 |
| 自编合成数据 | data/ 与 evaluation/build_data.py | 虚构API流；本工程MIT，不含真实用户或私有文档 | 自编模板、事件、任务与评分规格 |
| Ollama API | [官方接口](https://docs.ollama.com/api/chat) | 可选本地生成提取接入；未实测生成模型，模型许可须按实际选型另核对 | HTTP适配和跨度验证；不分发Ollama或模型 |
| Playwright / Chrome | 仅开发环境，用于浏览器验收和录屏 | 非产品运行依赖；不分发其程序 | 自编操作/截图/录制脚本 |
| ReportLab / Poppler / FFmpeg | 仅交付材料生成工具 | 非产品依赖；不分发其二进制或系统字体。输出不继承工具自身代码许可 | 自编排版和录制流程 |

完整实际运行依赖版本、包元数据中的原始许可字符串和来源链接记录在`output/environment.json`；锁文件为`requirements-semantic.lock`。NumPy、regex、tqdm等包含复合许可，不能仅凭本表的概括替代原始许可证。源码包未附带第三方权重、二进制或字体。

BGE文件哈希在本机`models/bge-small-zh-v1.5/manifest.json`，发布材料额外复制到`output/model-manifest.json`。锁定revision不等于自行审计全部权重来源，只说明本次使用的确定版本。

自主完成：事件协议与范围判断、重复证据关联、显式替代与冲突规则、来源授权检查、前缀回放、审计页、统一预算、合成评测及失败分析。不声称“版本、冲突或时间记忆”为首创。

参考项目[SimpleMem](https://github.com/aiming-lab/SimpleMem)、[Graphiti](https://github.com/getzep/graphiti)仅作为计划中的研究定位，未复用源码、未运行原生对照。不将B1简化基线称为它们的实现。生成AI参与范围见`ai-assistance.md`。
