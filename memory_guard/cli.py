from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import MemoryGuard
from .agent import run_agent
from .demo import load_demo


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Memory Guard · 记忆治理工作台")
    parser.add_argument("--db", default="runtime/memory.db")
    parser.add_argument("--stream", default="default")
    parser.add_argument("--extractor", choices=["rule", "ollama"], default="rule")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="载入六步模拟演示")
    sub.add_parser("snapshot")
    s = sub.add_parser("state")
    s.add_argument("--checkpoint", type=int)
    s = sub.add_parser("ingest")
    s.add_argument("file", help="JSON对象或JSONL文件；- 表示标准输入")
    s = sub.add_parser("correct")
    s.add_argument("target_id")
    s.add_argument("file")
    s = sub.add_parser("query")
    s.add_argument("--project", required=True)
    s.add_argument("--version", required=True)
    s.add_argument("--checkpoint", type=int)
    s.add_argument("--as-of")
    s.add_argument("--mode", choices=["character", "semantic", "hybrid"], default="character")
    s.add_argument("--budget", type=int, default=2048)
    s = sub.add_parser("inspect")
    s.add_argument("fact_id")
    s = sub.add_parser("export")
    s.add_argument("file")
    s = sub.add_parser("replay")
    s.add_argument("file")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s = sub.add_parser("evaluate")
    s.add_argument("--semantic", action="store_true")
    s.add_argument("--out", default="output/evaluation-v020")
    s.add_argument("--split", choices=["dev", "test", "all"], default="test")
    s = sub.add_parser('preview', help='在副本试写并报告旧任务变化；不保存事件')
    s.add_argument('file')
    s = sub.add_parser('impact', help='逐步回测历史学习影响')
    s.add_argument('--checkpoint', type=int)
    s = sub.add_parser('fork', help='恢复检查点到新的数据库，保留原历史')
    s.add_argument('file')
    s.add_argument('--checkpoint', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            if args.extractor != "rule":
                raise ValueError("网页演示固定使用规则提取；Ollama请通过 ingest CLI 写入后在页面查看")
            from .server import serve
            serve(args.db, args.port, args.stream)
            return
        if args.command == "evaluate":
            from evaluation.run_stream import evaluate
            emit(evaluate(args.out, args.semantic, args.split))
            return
        if args.command == "replay":
            m = MemoryGuard.replay(json.loads(Path(args.file).read_text(encoding="utf-8-sig")), args.db)
            emit({"checkpoint_id": m.snapshot(), "state_hash": m.state()["state_hash"]})
            m.close()
            return
        extractor = None
        if args.extractor == "ollama":
            from .extract import OllamaExtractor
            extractor = OllamaExtractor()
        encoder = None
        if getattr(args, "mode", "character") != "character":
            from .candidates import BGEEncoder
            encoder = BGEEncoder()
        m = MemoryGuard(args.db, stream_id=args.stream, extractor=extractor, encoder=encoder)
        try:
            if args.command == "demo":
                emit(load_demo(m))
            elif args.command == "snapshot":
                emit({"checkpoint_id": m.snapshot()})
            elif args.command == "state":
                emit(m.state(args.checkpoint))
            elif args.command == "ingest":
                text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8-sig")
                if not text.strip():
                    raise ValueError("输入文件为空")
                try:
                    parsed = json.loads(text)
                    events = parsed if isinstance(parsed, list) else [parsed]
                except json.JSONDecodeError:
                    events = [json.loads(line) for line in text.splitlines() if line.strip()]
                emit([m.ingest(e) for e in events])
            elif args.command == "correct":
                emit(m.correct(args.target_id, json.loads(Path(args.file).read_text(encoding="utf-8-sig"))))
            elif args.command == "query":
                emit(run_agent(m, {"project": args.project, "version_scope": args.version, "as_of": args.as_of}, checkpoint=args.checkpoint, mode=args.mode, token_budget=args.budget))
            elif args.command == "inspect":
                emit(m.inspect(args.fact_id))
            elif args.command == "export":
                Path(args.file).parent.mkdir(parents=True, exist_ok=True)
                Path(args.file).write_text(json.dumps(m.export(), ensure_ascii=False, indent=2), encoding="utf-8")
                emit({"exported": args.file, "checkpoint_id": m.snapshot()})
            elif args.command == 'preview':
                from .impact import prepare
                emit(prepare(m, json.loads(Path(args.file).read_text(encoding='utf-8-sig'))).report)
            elif args.command == 'impact':
                from .impact import history
                emit(history(m, args.checkpoint))
            elif args.command == 'fork':
                from .impact import fork
                if Path(args.file).exists():
                    raise ValueError('恢复目标已存在，请选择新的文件名')
                branch = fork(m, args.checkpoint, args.file)
                try:
                    emit({'path': args.file, 'checkpoint_id': branch.snapshot()})
                finally:
                    branch.close()
        finally:
            m.close()
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0
