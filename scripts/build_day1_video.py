"""Make a narrated replay of actual model logs; this is not a live screen capture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import wave

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"no_memory": "无跨任务记忆", "latest": "同范围最近优先", "governed": "MemoryGuard"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def metric(value):
    return f"{value['count']}/{value['total']}" if value['rate'] is not None else "不适用（分母 0）"


def output(row):
    prediction = row["prediction"]
    args = prediction.get("tool_args") or {}
    return [f"任务：{row['task']['project']} / {row['task']['version_scope']}",
            f"状态：{prediction['status']}", f"path: {args.get('path', '-')}",
            f"auth_field: {args.get('auth_field', '-')}", f"模拟工具：{row['execution']['code']}"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="output/evaluation-day1")
    parser.add_argument("--demo", default="output/day1-demo")
    parser.add_argument("--out", default="output/video/memoryguard-day1-demo.mp4")
    args = parser.parse_args()
    source, destination = Path(args.results), Path(args.out)
    progress, summary, config = (load(source / name) for name in ("progress.json", "summary.json", "config.json"))
    rows = [json.loads(line) for line in (source / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
    if progress["status"] != "complete" or len(rows) != summary["total_executions"]:
        raise ValueError("A complete real-model evaluation is required")
    if not all(r["prediction"].get("model_trace", {}).get("response") for r in rows):
        raise ValueError("Every shown execution must have a real service response")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for video authoring")
    destination.parent.mkdir(parents=True, exist_ok=True)
    work = ROOT / "runtime" / "day1-video"
    work.mkdir(parents=True, exist_ok=True)
    def row(method, stage, category):
        return next(r for r in rows if r["method"] == method and r["stage"] == stage and r["category"] == category)
    v1, v2 = row("governed", "learn_v1", "anchor"), row("governed", "learn_v2", "new")
    old = row("governed", "learn_v2", "anchor")
    latest, governed = (row(m, "duplicates_and_conflict", "anchor") for m in ("latest", "governed"))
    conflict, correction = (row("governed", stage, "new") for stage in ("duplicates_and_conflict", "authorized_correction"))
    methods = summary["methods"]
    demo = load(Path(args.demo) / "summary.json")
    recovery = demo["recovery"]
    dataset_count = summary["stream_count"]
    scenes = [
        ("让新知识进入，也保留旧任务", [
            ("面向持续学习智能体的记忆护栏", ["场景：开发助手持续接收 API 文档与纠错反馈。", "问题：版本并存、重复记录和冲突可能干扰后续调用。", "目标：观察新知识收益与仍有效旧任务的变化。"]),
            ("本片展示什么", ["真实模型运行记录回放", "固定权重的外部记忆适应", "本地模拟工具评分", "合成语音旁白；非实时录屏"]),
        ], "开发助手学习新接口后，旧版本可能仍然有效。记忆增加并不意味着每次调用都会更可靠。MemoryGuard把项目和版本、原文证据、重复记录、冲突与授权纠错放在同一条可追溯的流程中。本片按已经保存的真实模型记录回放过程，观察新知识学习与旧任务保留。模型权重保持固定，工具由本地模拟器评分。", 30),
        ("真实模型根据证据生成调用", [("学习 v1 后", output(v1)), ("学习 v2 后", output(v2))],
         "这里展示同一个本地模型在学习两个版本后的实际输出。路径和认证字段来自模型生成的结构化调用，不是用规则规划器替换的答案。模型只看到当前任务和取出的记忆证据；完整评分规格在生成结束后才交给模拟器。每次请求、原始响应、token用量和协议错误都随记录保存，后续可以逐条核验。", 31),
        ("版本并存，回测仍有效的 v1", [("学习 v2 后重做旧任务", output(old)), ("实验边界", ["普通记忆同样按项目、版本过滤。", "版本并存本身不保证治理方法胜出。", "旧答案仍有效，才可能形成退化配对。", "公开任务与答案哈希都必须相同。"] )],
         "学习第二版后，我们重新执行仍然有效的第一版任务。比较方法都获得项目和版本，并采用相同的范围过滤，因此不能靠剥夺基线的版本信息来制造优势。旧任务退化只统计公开任务与评分答案都没有变化、前一次已经成功的相邻配对。没有这样的配对时，比率记为不适用，不能写成零风险。", 30),
        ("重复记录会占用有限证据预算", [("普通记忆的实际输出", output(latest)), ("治理记忆的实际输出", output(governed))],
         "这一步向同一版本连续加入重复的路径记录。普通记忆保留原样观察，并按最近优先选取。有限证据预算可能被重复路径占满，认证字段因此消失。治理记忆合并重复事实，完整原文仍保存在审计中，任务上下文只保留代表证据。左右两侧都是实际输出；成功、澄清或错误均按保存的记录展示。", 33),
        ("冲突与授权纠错", [("矛盾证据到达后", output(conflict)), ("授权纠错之后", output(correction))],
         "新记录也可能与已有认证字段矛盾。治理方法先标记未决冲突，模型适配器会将已知缺证或冲突约束为澄清，防止工具调用越过记忆边界。证据充分时，调用参数仍由模型生成。之后由配置允许的维护者来源提交定向纠错，被替代事实保留在历史中。图中展示纠错前后真实的模型状态与模拟器结果。", 32),
        ("预检、确认和历史恢复", [("本次 SDK 演示记录", [f"模型调用：{demo['model_calls']} 次", f"模型错误：{demo['errors']} 次", "学习前：副本预检与原状态比较", "演示写入：脚本确认，不表示人工审核"]), ("恢复记录", [f"恢复检查点：{recovery['checkpoint']}", f"分支事件数：{recovery['event_count']}", f"原历史事件数：{recovery['original_events']}", "原始历史保留，恢复产生独立分支"] )],
         "学习前的预检会在副本试写，并比较旧任务的行为。这里的预检仍是确定性登录探针，不能把模型实验当成模型完整能力预检。演示脚本按预设流程确认写入，不代表有人完成审核。恢复检查点会创建独立分支，原始历史仍然保留。行为变化也不直接等于正确率，参数改变可能是正确适应，冲突时澄清也可能是必要保护。", 32),
        ("相同模型下的实际对照结果", [(LABELS[m], ["可回答任务成功：" + metric(methods[m]["success"]), "新任务成功：" + metric(methods[m]["new_task_success"]), "旧任务退化：" + metric(methods[m]["old_task_regression"]), f"模型错误：{methods[m]['planner_errors']}"]) for m in methods],
         f"本次共有{dataset_count}条合成任务流，三种方法合计执行{summary['total_executions']}次探针。表中保留成功数、分母、旧任务退化与模型错误，避免只展示成功案例。这些执行包含跨检查点重复的任务，不是同等数量的独立问题。场景由开发者编写且可见，结果支持当前记忆策略比较，不能据此宣称真实业务或通用智能体效果。", 31),
        ("代码、数据和记录都可复用", [("复现入口", ["python -m scripts.setup_local_planner", "python -m evaluation.day1 --help", "python -m examples.llm_agent --help", "python -m unittest discover -s tests -v"]), ("交付与后续", ["SDK / CLI / 本地工作台", "独立标签、配置与原始响应", "技术报告及资源使用说明", "报名与平台提交另行核实"] )],
         "可复用成果包括核心代码、Python接口、命令行、本地工作台、合成任务流、独立评分标签和原始响应。固定版本的模型与运行程序从官方来源获取，模型权重不进入源码包。报告同时说明自研边界、第三方资源与人工智能辅助开发。下一步是团队核对参赛授权和材料，并在比赛平台实际上传后核实回执。", 25),
    ]
    font_path = Path("C:/Windows/Fonts/Deng.ttf")
    bold_path = Path("C:/Windows/Fonts/Dengb.ttf")
    fonts = {s: ImageFont.truetype(str(font_path), s) for s in (24, 28, 32, 38, 48)}
    heading = ImageFont.truetype(str(bold_path), 42)
    def wrapped(draw, text, x, y, width, font, fill, spacing=12):
        line = ""
        for char in text:
            if draw.textlength(line + char, font=font) > width and line:
                draw.text((x, y), line, font=font, fill=fill)
                y += font.size + spacing
                line = ""
            line += char
        if line:
            draw.text((x, y), line, font=font, fill=fill)
            y += font.size + spacing
        return y
    manifest = []
    for index, (title, panels, speech, minimum) in enumerate(scenes, 1):
        frame = Image.new("RGB", (1920, 1080), "#eef3f8")
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 0, 1920, 150), fill="#152e46")
        draw.text((76, 40), title, font=heading, fill="white")
        draw.text((78, 105), "MEMORYGUARD  /  真实运行记录回放  /  本地 CPU", font=fonts[24], fill="#92d4d3")
        draw.text((1720, 52), f"{index:02}/08", font=fonts[38], fill="white")
        count = len(panels)
        panel_width = (1768 - (count - 1) * 32) // count
        for p, (label, lines) in enumerate(panels):
            x = 76 + p * (panel_width + 32)
            draw.rounded_rectangle((x, 202, x + panel_width, 852), radius=24, fill="white", outline="#d7e2ec", width=2)
            y = wrapped(draw, label, x + 32, 240, panel_width - 64, fonts[38], "#087e82") + 24
            for line in lines:
                y = wrapped(draw, line, x + 32, y, panel_width - 64, fonts[32], "#20384d") + 18
                if y > 830:
                    raise ValueError(f"Scene {index} overflows")
        footer = "证据数组预算 2048 UTF-8 字节；治理元数据在预算外。合成验证，非实时录屏。"
        wrapped(draw, footer, 78, 900, 1760, fonts[28], "#576c7d")
        draw.text((78, 1000), "来源：evaluation-day1 的 config / raw / summary 与 day1-demo 审计记录", font=fonts[24], fill="#576c7d")
        frame_path, wave_path = work / f"scene-{index:02}.png", work / f"scene-{index:02}.wav"
        frame.save(frame_path)
        manifest.append(dict(index=index, title=title, text=speech, image=str(frame_path), wav=str(wave_path), minimum=minimum))
    speech_manifest = work / "scenes.json"
    speech_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    speech_script = work / "speech.ps1"
    escaped_manifest = str(speech_manifest).replace("'", "''")
    speech_script.write_text("Add-Type -AssemblyName System.Speech\n$taskVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer\n$taskVoice.SelectVoice('Microsoft Huihui Desktop')\n$taskVoice.Rate = 0\ntry {\n" +
        f"$taskScenes = Get-Content -Raw -Encoding UTF8 -LiteralPath '{escaped_manifest}' | ConvertFrom-Json\n" +
        "foreach ($taskScene in $taskScenes) { $taskVoice.SetOutputToWaveFile($taskScene.wav); $taskVoice.Speak($taskScene.text) }\n} finally { $taskVoice.Dispose() }\n", encoding="utf-8-sig")
    shell = shutil.which('pwsh') or 'powershell'
    subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", speech_script.read_text(encoding='utf-8-sig')], check=True)
    durations, clips = [], []
    for scene in manifest:
        with wave.open(scene["wav"], "rb") as audio:
            spoken = audio.getnframes() / audio.getframerate()
        duration = max(spoken + 1, scene["minimum"])
        clip = work / f"scene-{scene['index']:02}.mp4"
        command = [ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-framerate", "1", "-i", scene["image"],
                   "-i", scene["wav"], "-t", str(duration), "-r", "24", "-c:v", "libx264", "-preset", "ultrafast",
                   "-tune", "stillimage", "-crf", "22", "-pix_fmt", "yuv420p", "-af", "apad", "-c:a", "aac", "-b:a", "128k", str(clip)]
        subprocess.run(command, check=True)
        clips.append(clip)
        durations.append(duration)
    concat = work / "concat.txt"
    concat.write_text("".join("file '" + p.as_posix() + "'\n" for p in clips), encoding="utf-8")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-c", "copy", "-movflags", "+faststart", str(destination)], check=True)
    total = sum(durations)
    if not 180 <= total <= 300 or destination.stat().st_size > 300 * 1024 * 1024:
        raise ValueError("Video does not meet duration or size requirements")
    checks = dict(duration_seconds=round(total, 3), width=1920, height=1080, bytes=destination.stat().st_size,
                  speech="Windows Huihui synthetic voice", source_config_hash=config["config_hash"],
                  presentation="replay of real logs, not live screen recording", scenes=[dict(title=s["title"], seconds=round(d, 3)) for s, d in zip(manifest, durations)])
    destination.with_suffix(".json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    thumbs = Image.new("RGB", (1280, 1440), "white")
    for i, scene in enumerate(manifest):
        image = Image.open(scene["image"])
        image.thumbnail((640, 360))
        thumbs.paste(image, ((i % 2) * 640, (i // 2) * 360))
    thumbs.save(destination.parent / "preview.png")
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
