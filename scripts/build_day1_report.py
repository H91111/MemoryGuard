"""Build the anonymous day-one report from a completed, traced model comparison.

Usage: python -m scripts.build_day1_report --results output/evaluation-day1
ReportLab is an authoring dependency, not a MemoryGuard runtime dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
TITLE = "面向持续学习智能体的记忆护栏"
MODEL = "Qwen/Qwen3-0.6B-GGUF"
MODEL_REVISION = "23749fefcc72300e3a2ad315e1317431b06b590a"
MODEL_URL = f"https://huggingface.co/{MODEL}/tree/{MODEL_REVISION}"
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/tag/b11951"
LABELS = {"no_memory": "无跨任务记忆", "latest": "同范围最近优先", "governed": "MemoryGuard"}
STAGES = {"learn_v1": "学习 v1", "learn_v2": "学习 v2", "duplicates_and_conflict": "重复与冲突", "authorized_correction": "授权纠错"}
NAVY = colors.HexColor("#172E46")
TEAL = colors.HexColor("#087E82")
ORANGE = colors.HexColor("#D17C22")
MUTED = colors.HexColor("#566879")
LIGHT = colors.HexColor("#EEF4F6")
PAGE_W, PAGE_H = A4


def metric_text(metric):
    count, total, rate = metric["count"], metric["total"], metric["rate"]
    return f"{count}/{total}（{rate:.1%}）" if rate is not None else f"{count}/{total}（不适用）"


def short_prediction(row):
    p = row["prediction"]
    if p["status"] == "call":
        a = p.get("tool_args") or {}
        return f"调用 {a.get('path', '?')}，认证字段 {a.get('auth_field', '?')}；模拟器 {row['execution']['code']}"
    return f"{p['status']}：{p.get('reason', '')[:120]}"


class Pipeline(Flowable):
    def __init__(self, width=483, height=152):
        super().__init__()
        self.width, self.height = width, height

    def draw(self):
        c, box_w = self.canv, 104
        nodes = [(0, 88, "文档 / 反馈", "保留原文与范围"), (126, 88, "记忆治理", "去重 / 冲突 / 纠错"),
                 (252, 88, "范围内检索", "统一证据预算"), (378, 88, "模型规划", "调用或澄清"),
                 (126, 10, "副本预检", "确定性登录探针"), (378, 10, "独立模拟评分", "模型返回后读答案")]
        for x, y, title, subtitle in nodes:
            c.setFillColor(LIGHT)
            c.setStrokeColor(colors.HexColor("#D2E0E5"))
            c.roundRect(x, y, box_w, 48, 6, fill=1, stroke=1)
            c.setFillColor(NAVY)
            c.setFont("CJK-Bold", 10)
            c.drawCentredString(x + box_w / 2, y + 29, title)
            c.setFillColor(MUTED)
            c.setFont("CJK", 8)
            c.drawCentredString(x + box_w / 2, y + 13, subtitle)
        c.setStrokeColor(TEAL)
        for left in (104, 230, 356):
            c.line(left, 112, left + 20, 112)
            c.line(left + 16, 115, left + 20, 112)
            c.line(left + 16, 109, left + 20, 112)
        c.line(178, 88, 178, 60)
        c.line(430, 88, 430, 60)


class LearningCurve(Flowable):
    def __init__(self, methods):
        super().__init__()
        self.width, self.height, self.methods = 483, 244, methods

    def draw(self):
        c, left, bottom, width, height = self.canv, 42, 49, 410, 155
        c.setFont("CJK", 8)
        for tick in (0, 25, 50, 75, 100):
            y = bottom + tick * height / 100
            c.setStrokeColor(colors.HexColor("#DFE7EB"))
            c.line(left, y, left + width, y)
            c.setFillColor(MUTED)
            c.drawRightString(left - 8, y - 3, f"{tick}%")
        stages = list(next(iter(self.methods.values()))["per_stage"])
        xs = [left + i * width / max(1, len(stages) - 1) for i in range(len(stages))]
        for x, row in zip(xs, stages):
            c.setFillColor(MUTED)
            c.drawCentredString(x, bottom - 20, STAGES.get(row["stage"], row["stage"]))
        for index, (method, color) in enumerate(zip(LABELS, (MUTED, ORANGE, TEAL))):
            points = self.methods[method]["per_stage"]
            c.setStrokeColor(color)
            c.setFillColor(color)
            c.setLineWidth(2)
            values = [100 * row["success"] / row["answerable"] if row["answerable"] else None for row in points]
            for i in range(1, len(points)):
                if values[i-1] is not None and values[i] is not None:
                    c.line(xs[i-1], bottom + values[i-1]*height/100, xs[i], bottom + values[i]*height/100)
            for x, value in zip(xs, values):
                if value is not None:
                    c.circle(x, bottom + value*height/100, 3, fill=1, stroke=0)
            x = left + index * 145
            c.line(x, 229, x + 18, 229)
            c.setFont("CJK", 8)
            c.drawString(x + 23, 226, LABELS[method])
        c.setFillColor(MUTED)
        c.setFont("CJK", 8)
        c.drawString(left, 5, "每个检查点：可回答任务成功数 / 可回答任务数；冲突及无知识任务不计入分母。")


def register_fonts():
    candidates = [Path("C:/Windows/Fonts/Deng.ttf"), Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf")]
    regular = next((p for p in candidates if p.exists()), None)
    if not regular:
        raise RuntimeError("Set up a Chinese TrueType font before building this Chinese report")
    bold = regular.with_name("Dengb.ttf") if regular.name == "Deng.ttf" else regular
    pdfmetrics.registerFont(TTFont("CJK", str(regular)))
    pdfmetrics.registerFont(TTFont("CJK-Bold", str(bold)))
    pdfmetrics.registerFontFamily("CJK", normal="CJK", bold="CJK-Bold", italic="CJK", boldItalic="CJK-Bold")


def build(results, output):
    config = json.loads((results / "config.json").read_text(encoding="utf-8"))
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    progress = json.loads((results / "progress.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (results / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
    if progress["status"] != "complete" or len(rows) != summary["total_executions"] or len(rows) != config["planned_executions"]:
        raise ValueError("Report requires the complete evaluation and matching raw records")
    if not any(r["prediction"].get("model_trace", {}).get("response") for r in rows):
        raise ValueError("No real model response in evaluation; deterministic smoke results cannot become this report")
    register_fonts()
    output.parent.mkdir(parents=True, exist_ok=True)
    body = ParagraphStyle("body", fontName="CJK", fontSize=10.2, leading=17.3, textColor=NAVY,
                          spaceAfter=9, wordWrap="CJK", allowWidows=0, allowOrphans=0)
    sub = ParagraphStyle("sub", parent=body, fontName="CJK-Bold", fontSize=13.5, leading=20, spaceBefore=13, spaceAfter=10)
    small = ParagraphStyle("small", parent=body, fontSize=8.4, leading=13.5, textColor=MUTED, spaceAfter=7)
    title_style = ParagraphStyle("title", parent=body, fontName="CJK-Bold", fontSize=27, leading=38, spaceAfter=20)
    chapter_style = ParagraphStyle("chapter", parent=body, fontName="CJK-Bold", fontSize=21, leading=30, spaceAfter=20)
    styles = dict(body=body, sub=sub, small=small)
    story, markdown = [], []

    def p(text, style="body"):
        story.append(Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style]))
        markdown.append(str(text) + "\n")

    def heading(number, title):
        if story:
            story.append(PageBreak())
        story.append(Paragraph(f"{number:02d} / MEMORYGUARD", small))
        story.append(Paragraph(escape(title), chapter_style))
        markdown.append(f"\n## {number}. {title}\n")

    def table(data, widths):
        wrapped = [[Paragraph(escape(str(v)).replace("\n", "<br/>"), small if i else ParagraphStyle("th", parent=small, fontName="CJK-Bold", textColor=colors.white)) for v in row] for i, row in enumerate(data)]
        t = Table(wrapped, colWidths=widths, hAlign="LEFT", repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT, colors.white]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, NAVY),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#D2E0E5")),
        ]))
        story.extend([t, Spacer(1, 11)])
        md_rows = ["| " + " | ".join(str(v).replace("\n", " / ") for v in row) + " |" for row in data]
        md_rows.insert(1, "| " + " | ".join("---" for _ in data[0]) + " |")
        markdown.append("\n".join(md_rows) + "\n")

    methods = summary["methods"]
    m, baseline = methods["governed"], methods["latest"]
    model_calls = sum(r["prediction"].get("generation_model_calls", 0) for r in rows)
    error_count = sum(v["planner_errors"] for v in methods.values())
    completed_responses = sum(bool(r["prediction"].get("model_trace", {}).get("response")) for r in rows)
    usage = Counter()
    for row in rows:
        usage.update({k: v for k, v in (row["prediction"].get("token_usage") or {}).items() if isinstance(v, int)})

    story.append(Paragraph("AI 开发工具与开源协作 · 技术报告", small))
    story.append(Spacer(1, 48))
    story.append(Paragraph(TITLE, title_style))
    p("MemoryGuard", "sub")
    p("让 API 文档更新成为可检查、可追溯的记忆变化。")
    story.append(Spacer(1, 20))
    table([["本次运行", "已保存证据"],
           [f"{summary['stream_count']} 条合成任务流，{summary['total_executions']} 次任务执行", "配置、任务流、独立答案、逐次原始请求与响应"],
           [f"治理记忆成功：{metric_text(m['success'])}", f"普通记忆成功：{metric_text(baseline['success'])}"],
           [f"治理旧任务退化：{metric_text(m['old_task_regression'])}", f"普通记忆旧任务退化：{metric_text(baseline['old_task_regression'])}"],
           [f"真实模型请求：{model_calls}；规划错误：{error_count}", "固定 Qwen3-0.6B Q8_0，CPU 本地推理"]], [241, 242])
    p("作品面向持续接收项目文档与纠错反馈的开发助手。模型权重保持固定，通过外部记忆学习新 API；记忆治理处理范围、重复、冲突和授权替代。工具执行由独立本地模拟器评分。", "body")
    p("本报告只解释本次开发者可见的合成对照结果；不将历史规则回归、开发过程使用 AI 或未运行接口计入生成模型效果。", "small")
    p("2026 年 10 月 28 日 · 匿名评审材料", "small")
    markdown.insert(0, f"# {TITLE}\n\n2026-10-28 · 本地合成验证\n")

    heading(2, "场景与研究问题")
    p("开发助手常常需要记住一个项目多个版本的 API。新文档并不总是替代旧文档：仍在维护的 v1 客户端继续使用 v1 路径，新客户端则需要 v2 的认证字段。重复消息、未经确认的笔记和后续纠错会同时进入记忆。")
    p("研究问题是：学习新知识后，助手能否提高新任务表现，同时保留答案仍然有效的旧任务？这里的持续学习采用固定权重下的非参数外部记忆适应，工程未实现模型参数训练。")
    p("四类连续场景", "sub")
    table([["场景", "观察重点"], ["版本并存", "学习 v2 后仍可完成合法 v1 任务；普通基线也获得项目、版本过滤。"],
           ["正常知识学习", "v2 证据到达前应澄清，到达后能生成适用调用。"],
           ["重复信息干扰", "同一 v1 属性的重复观察会否挤出另一个必需属性。"],
           ["冲突与授权纠错", "证据矛盾时合理澄清，确认替代后恢复调用。"]], [105, 378])
    p("负影响的判定", "sub")
    p("仅当同一旧任务在前次检查点成功、前后均可回答、公开任务哈希及评分答案哈希均相同时，才把它纳入退化率分母。更新后失败计为退化。合法的 API 变更和真实冲突下的澄清，不被自动判为遗忘。分母为 0 时报告不适用。")
    p("目标使用者是本机操作的开发者。当天范围限定一个助手、一个固定模型、一类登录工具与上述四类记忆场景；多租户、模型训练和真实业务 API 执行不在本次交付范围。")

    heading(3, "实现架构与信息边界")
    story.append(Pipeline())
    story.append(Spacer(1, 12))
    p("上图实线表示本次任务执行主链路。副本预检与独立评分分别服务更新决策和实验判定，二者不共享隐藏答案。")
    table([["层次", "实现与作用"], ["持久化与审计", "SQLite 追加事件、事实、证据、关系及决策，保留检查点前缀。"],
           ["提取与记忆治理", "规则提取带原文跨度的 API 属性；范围隔离、重复证据关联、冲突保留、授权纠错。"],
           ["检索与预算", "按项目、版本及所需属性检索；治理上下文每个事实保留一份代表证据，审计库保留完整证据。"],
           ["真实模型规划", "ChatPlanner 向本地 chat-completions 服务发送任务与证据，生成结构化调用或澄清。"],
           ["独立评分", "mock_api_call 在模型返回后检查项目、版本、路径与认证字段；不发业务网络请求。"]], [105, 378])
    p("模型只能看到白名单内的公开任务字段和方法提供的上下文，task_id 等管理字段不进入模型输入；它不接收未来事件、评分标签、模拟工具规格或评分结果回写。探针前后记忆状态哈希必须一致，避免评测任务本身成为额外学习。")
    p("工作台仍使用确定性规划器；真实模型入口位于 Python SDK、CLI 和 day1 评测。此次接入没有把工作台预检改造成真实模型全能力预检。", "small")

    heading(4, "记忆更新、冲突与可恢复性")
    p("每条输入包含项目、版本、来源和原文。规则提取候选值并检查它能否在原文证据跨度中逐字找到；含条件、否定或缺失范围的输入保留待复核，避免把含糊文字直接转成明确事实。")
    table([["机制", "实现结果"], ["版本隔离", "不同项目、版本或不重叠有效区间的事实可并存，任务只读取适用范围。"],
           ["重复关联", "同一逻辑事实关联新增证据；检索保留代表证据与计数，审计不删原文。"],
           ["冲突保留", "同范围、同属性出现不同值时保留冲突；检测发生在上下文截断之前。"],
           ["授权纠错", "本机策略允许 maintainer 指定当前事实进行替代，保留 supersedes 关系和历史。"],
           ["恢复与回放", "从检查点创建独立历史分支；导出审计包、回放和状态摘要核验支持恢复。"]], [105, 378])
    p("副本预检的实际责任", "sub")
    p("prepare 固定一次提取结果，在独立副本试写，并在前后状态运行相同登录任务。报告呈现调用保持、阻断、参数变化、恢复及持续不可用；commit 核对原状态、预检指纹与风险确认后提交冻结候选。")
    p("这是一组行为信号，不等于有真值的正确率。默认自动探针只覆盖已知项目/版本的登录任务，仍由确定性规划器执行。直接 ingest 等入口仍存在；需要强制门控的宿主应收敛写入接口。")

    heading(5, "真实 AI 的作用与运行记录")
    p(f"本次真实模型为 {MODEL} 的 Q8_0 GGUF 权重，revision 为 {MODEL_REVISION}；推理服务采用 llama.cpp b11951 的 Windows CPU 构建。权重固定，没有微调。")
    p("共享适配器保留记忆可用性门控：已知缺证、冲突或不支持的范围将 schema 约束为 clarify，模型生成澄清文本；证据充分时，模型根据自然语言任务及记忆选择调用及路径、认证字段、工具参数和引用。适配层验证协议、范围和载荷，不用规则规划器修补参数，也不访问评分规格。错误路径由模拟器判失败。缺证/冲突时的澄清决策不归因于模型独立识别。")
    planner = config["planner"]
    table([["生成设置", "本次配置"], ["温度 / 随机种子", f"{planner.get('temperature', '见 config')} / {planner.get('seed', '见 config')}"],
           ["输出预算 / thinking", f"{planner.get('max_tokens', '见 config')} tokens / 关闭"],
           ["结构化响应", "JSON schema：status、tool_args、evidence_ids、reason"],
           ["请求与响应", f"{model_calls} 次模型请求；{completed_responses} 条服务响应；{error_count} 次规划错误"],
           ["token 用量", f"prompt {usage.get('prompt_tokens', 0)}；completion {usage.get('completion_tokens', 0)}；total {usage.get('total_tokens', 0)}"],
           ["失败处理", "单请求、无自动重试；错误单列并按任务失败保留。"]], [150, 333])
    p("每次 raw.jsonl 记录任务、上下文、完整请求、原始响应、解析结果、token 用量和模拟执行结果。网络或格式失败记录为 error；澄清只在模型明确返回 clarify 时统计。")
    p("模型调用证据与原始响应保存在本地结果包。BGE/Ollama 是既有可选接口，此报告没有将其作为本次已运行的模型。", "small")

    heading(6, "公平比较与评分协议")
    p(f"本次采用 {summary['stream_count']} 条 acceptance 任务流，每条 4 个检查点、每检查点 3 个探针，三种方法共 {summary['total_executions']} 次执行。开发集与验收集采用不同项目和任务 ID，但共享自编构造骨架；这些数据是开发者可见的合成样例，不是独立盲测。")
    table([["方法", "上下文策略"], ["无跨任务记忆", "每次只给当前任务，无历史证据；仍实际调用相同模型。"],
           ["同范围最近优先", "按相同项目、版本和所需属性过滤原样观察，再按最近优先截断。"],
           ["MemoryGuard", "相同输入事件，规则治理、重复合并、冲突前置检测、授权替代及字符检索。"]], [130, 353])
    p(f"三组使用相同提示词模板、生成参数和事实投影，上下文证据预算为 {config['budget']} 字节、top-k={config['top_k']}。字节数按 canonical JSON facts 数组的 UTF-8 编码计量；task、system、schema 及 status/missing/conflicts 等治理元数据在证据预算外，各组完整提示词长度不一定相同。真实 tokenizer 用量另记。")
    table([["指标", "分母"], ["可回答 / 新任务成功率", "独立评分标签判可回答的任务 / 其中 category=new 的任务。"],
           ["旧任务退化率", "前次成功、前后可答，公开任务哈希与评分答案哈希均相同的相邻旧任务配对。"],
           ["错误调用率", "分别报告错误调用 / 全部执行，以及错误调用 / 实际调用。"],
           ["多余澄清率", "可回答任务中模型返回 clarify 的次数。"],
           ["正确澄清率", "不可回答任务中模型返回 clarify 的次数；error 不算澄清。"]], [130, 353])
    p("配置与输入/评分哈希在执行前保存。评分标签仅在模型返回后进入模拟器，任务输出不回写记忆。该实验比较整套记忆策略，没有单独的预检关闭消融，因此不单独归因预检收益。", "small")

    heading(7, "本次对照结果与学习过程")
    table([["方法", "可回答成功", "新任务成功", "旧任务退化"], *[
        [LABELS[method], metric_text(v["success"]), metric_text(v["new_task_success"]), metric_text(v["old_task_regression"])] for method, v in methods.items()]], [105, 126, 126, 126])
    table([["方法", "错误调用 / 全部", "多余澄清", "规划错误"], *[
        [LABELS[method], metric_text(v["wrong_call"]), metric_text(v["excess_clarify"]), str(v["planner_errors"])] for method, v in methods.items()]], [105, 135, 153, 90])
    p(f"治理组新任务成功 {metric_text(m['new_task_success'])}，普通记忆为 {metric_text(baseline['new_task_success'])}，并非所有指标均改善。旧任务配对分母也因各方法先前是否成功而异，逐对记录随汇总保存。", "small")
    story.append(LearningCurve(methods))
    p("曲线按检查点汇总可回答任务的表现，不能把同一流内多次探针当作独立用户样本。版本并存阶段的两种有记忆方法均可能成功；重复与冲突阶段才检验不同上下文策略的影响。", "small")
    p(f"本次运行耗时 {summary['elapsed_seconds']:.1f} 秒；这些数字来自本次 config/raw/summary，不沿用 output/evaluation-v020 的历史规则规划成绩。", "small")

    heading(8, "两个可核验案例")
    grouped = {}
    for row in rows:
        grouped.setdefault((row["stream_id"], row["task"]["task_id"]), {})[row["method"]] = row
    gain = next((g for g in grouped.values() if g.get("governed", {}).get("success") and not g.get("latest", {}).get("success") and g["governed"]["category"] == "anchor"), None)
    if gain is None:
        gain = next((g for g in grouped.values() if "governed" in g and "latest" in g and g["governed"]["category"] == "anchor" and g["governed"]["stage"] == "duplicates_and_conflict"), next(iter(grouped.values())))
    p("案例一：重复观察下仍有效的旧任务", "sub")
    exemplar = gain["governed"]
    p(f"任务：{exemplar['task']['task_id']}。项目 {exemplar['task']['project']} / {exemplar['task']['version_scope']}，检查点 {exemplar['step']}；评分答案哈希 {exemplar['answer_hash'][:16]}。")
    for method in ("latest", "governed"):
        row = gain[method]
        p(f"{LABELS[method]}：上下文 {len(row['context']['facts'])} 条事实、{row['context']['context_units']} 字节；{short_prediction(row)}。", "small")
    p("原样观察会为相同属性的每次出现支付上下文成本。治理方法合并逻辑事实，同时保留审计证据；本例只能支持这套记忆与上下文策略的整体比较。若两方法都失败，仍按失败报告。")
    failures = [g for g in grouped.values() if "governed" in g and g["governed"]["answerable"] and not g["governed"]["success"]]
    second = failures[0] if failures else next((g for g in grouped.values() if g.get("governed", {}).get("stage") == "authorized_correction" and g["governed"]["category"] == "new"), next(iter(grouped.values())))
    row = second["governed"]
    p("案例二：" + ("保留治理方法的失败" if failures else "冲突纠正后的恢复"), "sub")
    p(f"任务：{row['task']['task_id']}；检查点 {row['step']}，stage={row['stage']}。")
    for method in ("latest", "governed"):
        p(f"{LABELS[method]}：{short_prediction(second[method])}。", "small")
    p("冲突后的合理澄清是所需行为；授权纠错要显式替代原事实，不能只把一条新笔记自动视为正确。报告保留模型本身的输出和错误，并将记忆策略效果与模型波动分开理解。")
    p("完整记录定位：结果目录 raw.jsonl，使用本页 task_id 与 method 搜索；评分文件 scoring-labels.jsonl 与输入 streams.jsonl 分开保存。", "small")
    repeats_path = results / 'repeats-summary.json'
    if repeats_path.exists():
        repeats = json.loads(repeats_path.read_text(encoding='utf-8'))
        p(f"另对 {repeats['selected_cases']} 个已保存失败案例按相同 temperature/seed 各复跑两次，共 {repeats['model_calls']} 次调用；状态及参数与原记录相同 {repeats['unchanged']}/{repeats['model_calls']}。复跑单独保存，不加入原实验分母，也不据此估计一般模型波动。", "small")

    heading(9, "复现、演示与开放成果")
    p("核心软件支持 Python 3.11+，默认离线规则模式无第三方依赖。本次模型规划另外使用项目内下载的 CPU 推理运行时和权重，二者不随源码重新授权。Windows 复现步骤如下。")
    table([["步骤", "命令或产物"], ["1. 核心回归", "python -m unittest discover -s tests -v"],
           ["2. 准备并启动模型", "python -m scripts.setup_local_planner --start"],
           ["3. 三组同模型比较", "python -m evaluation.day1 --split acceptance --out output/evaluation-day1-rerun"],
           ["4. 生成本报告", "python -m scripts.build_day1_report --results output/evaluation-day1-rerun"],
           ["5. 启动工作台", "powershell -File start.ps1 -Port 8765"],
           ["6. 学习门控示例", "python -m examples.lifelong_agent"]], [123, 360])
    p("结果输出目录必须不存在，避免覆盖历史。固定模型、运行时、生成参数和数据哈希见 config、模型 manifest 与运行时 manifest。CPU 性能和模型运行库可能影响耗时及输出，复现应保留新的原始记录。")
    p("演示次序", "sub")
    p("先展示 v1 与 v2 合法并存，再对仍有效的 v1 任务回测。加入重复记录或冲突后，查看上下文、行为变化和原文证据。经过授权纠错恢复，再从历史检查点建立新分支，证明原始历史仍可追溯。")
    p("真实模型演示使用 CLI/SDK 与本次 raw.jsonl；工作台预检与恢复展示现有确定性流程。两部分在视频中分别标注，避免把预检行为信号说成模型正确率。")
    p("可复用成果包括核心源码、规则与模型适配入口、公开合成输入及独立评分标签、评测命令、原始运行记录、技术报告与操作说明。外部成果链接和上传状态需在提交前另行核实。")

    heading(10, "第三方资源与 AI 辅助披露")
    table([["资源", "来源 / 版本 / 许可", "使用方式"], ["Python / SQLite", "本次 Python " + config["python"] + " / SQLite 3.53.1；沿用上游许可", "存储、CLI、HTTP 及评测。"],
           ["Qwen3-0.6B Q8_0", "Qwen 官方 GGUF；固定 revision；Apache-2.0", "CPU 生成结构化工具计划；不训练、不修改权重。"],
           ["llama.cpp", "ggml-org b11951；MIT", "本机 CPU 推理服务；单独下载运行时。"],
           ["ReportLab / Poppler", "ReportLab 4.4.9；本地材料工具；沿用各自许可", "报告排版与渲染核验，不是产品运行依赖。"],
           ["合成数据", "本工程自编；随项目 MIT", "虚构 API 场景，不含真实用户或私有文档。"],
           ["BGE / Ollama", "既有可选接入；未计本次模型效果", "许可按具体模型与接口分别说明。"]], [95, 225, 163])
    p("自研边界", "sub")
    p("本工程实现事件协议、范围判断、证据跨度校验、重复关联、冲突与授权替代、前缀回放、副本预检及门控、会话恢复、统一预算、模型 HTTP 适配、合成评测和结果分析。基础模型、推理引擎及第三方运行库来自上游，不声称为自研。")
    p("AI 辅助开发说明", "sub")
    p("在既有 v0.2.0 原型上，Codex 协助阅读代码、实现模型规划适配与评测流程、生成合成数据、执行检查、分析运行记录和排版材料。应用运行时的 Qwen 推理与开发过程的 AI 协助分开披露。最终用途、来源授权、个人/团队角色和提交前人工审核由实际参赛者确认；本报告不把这些待确认事项写成已完成。")
    p("模型官方来源：" + MODEL_URL, "small")
    p("推理引擎官方来源：" + LLAMA_URL, "small")

    heading(11, "适用边界与提交核对")
    p("本次证据支持的结论", "sub")
    p(f"在 {summary['stream_count']} 条开发者可见合成流和相同模型参数下，MemoryGuard 可回答成功为 {metric_text(m['success'])}，同范围最近优先为 {metric_text(baseline['success'])}。旧任务退化分别为 {metric_text(m['old_task_regression'])} 与 {metric_text(baseline['old_task_regression'])}。这是整套记忆治理与上下文组织的局部工程验证。")
    p("尚不能由本次结果推出的结论", "sub")
    p("该样本规模和单一 API 类型不能代表通用 Agent、真实业务 API 或真人使用效果；没有独立盲标、多模型对比或预检模块消融。固定小模型可能出现格式与参数错误。默认预检只覆盖固定登录探针，存在直接写入路径。本机 maintainer 来源标签不等于多用户身份认证。")
    p("提交前还需核实", "sub")
    table([["事项", "当前口径"], ["报名、缴费、团队与成果授权", "本地代码和实验记录无法证明，需参赛者核实。"],
           ["报告与简介", "本报告及提交说明由本次结果生成；不含学校、LOGO 或指导教师信息。"],
           ["视频", "按独立视频产物与脚本核对，真实模型与确定性工作台需分别标明。"],
           ["成果链接", "正式发布位置与评审期可访问性需提交前验证。"],
           ["最终上传", "本报告生成不代表比赛平台提交成功。"]], [145, 338])
    p("证据索引", "sub")
    p(f"协议：{config['protocol']}；配置哈希：{config['config_hash']}。", "small")
    p("输入哈希：" + config["input_sha256"] + "；评分哈希：" + config["scoring_sha256"] + "。", "small")
    p("材料依据：仓库 HANDOFF.md、evaluation/configs/day1.md、memory_guard/{agent,llm,impact,store}.py、evaluation/day1.py 及本次结果目录。赛事格式与截止时间以提交时官方通知和比赛平台为准。", "small")

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(TEAL)
        canvas.rect(0, PAGE_H - 10, PAGE_W, 10, fill=1, stroke=0)
        canvas.setStrokeColor(colors.HexColor("#D9E4E8"))
        canvas.line(56, 43, PAGE_W - 56, 43)
        canvas.setFont("CJK", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(56, 28, "MemoryGuard / 技术报告 / 2026-10-28")
        canvas.drawRightString(PAGE_W - 56, 28, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=56, leftMargin=56,
                            topMargin=51, bottomMargin=58, title=TITLE, author="",
                            subject="外部记忆治理与同模型合成比较", creator="MemoryGuard report generator")
    doc.build(story, onFirstPage=page, onLaterPages=page)
    md_path = ROOT / "docs/day1-report.md"
    md_path.write_text("\n".join(markdown), encoding="utf-8")
    metadata = {"file": str(output.relative_to(ROOT)), "bytes": output.stat().st_size,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "results": str(results),
                "config_hash": config["config_hash"], "expected_pages": 11, "anonymous": True}
    from pypdf import PdfReader
    metadata["pages"] = len(PdfReader(output).pages)
    if metadata["pages"] != 11 or metadata["bytes"] >= 10_000_000:
        raise ValueError(f"Report layout/size requirement failed: {metadata}")
    (output.parent / "report-checks.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    write_submission(summary, config)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


def write_submission(summary, config):
    ours, latest = summary["methods"]["governed"], summary["methods"]["latest"]
    intro = ("面向持续接收 API 文档的开发助手，MemoryGuard 通过范围隔离、重复证据合并、冲突处理、授权纠错和可追溯恢复管理外部记忆。"
             "共享门控约束已知缺证和冲突，固定 Qwen3-0.6B 本地模型生成调用参数与澄清文本，由独立模拟器评分。"
             f"在{summary['stream_count']}条合成流、{summary['total_executions']}次执行中，治理与普通记忆的可回答任务成功数分别为"
             f"{ours['success']['count']}/{ours['success']['total']}和{latest['success']['count']}/{latest['success']['total']}；"
             f"旧任务退化为{ours['old_task_regression']['count']}/{ours['old_task_regression']['total']}和{latest['old_task_regression']['count']}/{latest['old_task_regression']['total']}。"
             "开放源码、合成输入、独立评分及原始记录。结果限于本次合成验证。")
    if len(intro) > 300:
        raise ValueError("Submission introduction exceeds 300 characters")
    text = f"""# Day-one 初赛材料\n\n作品名称：{TITLE}\n\n建议方向：AI 开发工具与开源协作\n\n## 简介（{len(intro)} 字符）\n\n{intro}\n\n## 约四分钟视频脚本\n\n| 时间 | 画面与操作 | 解说要点 |\n|---|---|---|\n| 0:00-0:30 | 作品标题与开发助手场景 | 新 API 文档到达时，旧版本仍需服务；重复和冲突会影响后续调用。 |\n| 0:30-1:20 | CLI/SDK 真实模型记录，v1 再 v2 | 固定 Qwen3-0.6B 根据当前证据生成参数；路径与认证字段来自模型输出，评分来自独立模拟器。 |\n| 1:20-2:05 | 重复干扰，对照 latest/governed 的上下文及旧任务 | 相同范围过滤和预算；原样观察会重复占位，治理合并证据。只按真实记录展示成功或失败。 |\n| 2:05-2:50 | 工作台冲突预检、证据、授权纠错和历史分支 | 此处明确标注“确定性登录探针”；行为变化并不等于正确率。恢复创建分支，原历史保留。 |\n| 2:50-3:30 | 本次结果表、学习曲线与两个案例 | {summary['total_executions']}次执行是重复探针而非独立问题；旧任务退化只计答案仍有效的前次成功配对。 |\n| 3:30-4:00 | 代码、数据、运行说明及材料目录 | 展示可复用入口与原始请求响应；合成验证、单模型、模拟工具的范围如实说明。 |\n\n视频需要同时呈现实际操作和可读的真实运行记录；此脚本本身不表示 MP4 已录制或已提交。\n\n## 产物与提交前核对\n\n- 技术报告：`output/pdf/memoryguard-day1-report.pdf`。\n- 可编辑报告内容：`docs/day1-report.md`。\n- 实验：本次结果目录的 `config.json`、`streams.jsonl`、`scoring-labels.jsonl`、`raw.jsonl`、`summary.json`。\n- 检查视频 MP4 3-5 分钟、300MB 以内，报告 PDF 10MB 以内。\n- 核实匿名要求、第三方资源与 AI 辅助披露，保持所有结果口径一致。\n- 报名、缴费、团队归属、参赛授权、外部成果链接及上传回执仍须实际核实，不能由本地材料推断。\n\n配置哈希：`{config['config_hash']}`。本简介由完成的本次结果自动生成，数字不沿用历史规则回归。\n"""
    video_path = ROOT / 'output/video/memoryguard-day1-demo.json'
    if video_path.exists():
        video = json.loads(video_path.read_text(encoding='utf-8'))
        def stamp(seconds):
            return f'{int(seconds)//60}:{int(seconds)%60:02}'
        chapter = '## 视频（实际运行记录回放）\n\n'
        chapter += f"已生成 `output/video/memoryguard-day1-demo.mp4`，{video['duration_seconds']:.1f} 秒，{video['width']}×{video['height']}，{video['bytes']:,} 字节。含系统合成语音，非实时录屏。\n\n| 时间 | 内容 |\n|---|---|\n"
        elapsed = 0
        for scene in video['scenes']:
            end = elapsed + scene['seconds']
            chapter += f"| {stamp(elapsed)}-{stamp(end)} | {scene['title']} |\n"
            elapsed = end
        before, rest = text.split('## 约四分钟视频脚本', 1)
        after = rest[rest.index('## 产物与提交前核对'):]
        text = before + chapter + '\n' + after
    (ROOT / "docs/day1-submission.md").write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "output/evaluation-day1")
    parser.add_argument("--out", type=Path, default=ROOT / "output/pdf/memoryguard-day1-report.pdf")
    args = parser.parse_args()
    build(args.results.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
