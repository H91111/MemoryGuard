"""Prefix-only evaluator. Memory/planner never receive labels or tool specs."""
from __future__ import annotations

import json
import platform
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

from memory_guard import MemoryGuard
from memory_guard.agent import plan
from memory_guard.candidates import BGEEncoder, MODEL_ID, MODEL_REVISION, rank
from memory_guard.extract import RuleExtractor
from memory_guard.schema import canonical, digest, stable_id
from examples.api_agent.mock_tool import mock_api_call
from .negative_impact import summarize

ROOT = Path(os.environ.get("MEMORY_GUARD_WORKSPACE", Path.cwd()))
METHODS = {
    "B0": ("无跨任务记忆", "none"),
    "B1": ("普通向量记忆", "semantic"),
    "B2": ("同范围最近优先", "latest"),
    "B3": ("规则 + 字符检索", "character"),
    "Ours": ("规则 + 联合检索", "hybrid"),
    "A1": ("消融：移除范围过滤", "hybrid"),
    "A2": ("消融：移除更新治理", "hybrid"),
}


class CachedExtractor:
    """All methods share the exact frozen candidates, not evaluation labels."""
    revision = RuleExtractor.revision

    def __init__(self, shared):
        self.shared = shared

    def extract(self, event):
        candidates, errors = self.shared[event["event_id"]]
        return json.loads(json.dumps(candidates)), list(errors)


def raw_context(raw, task, cp, backend, encoder, budget, top_k):
    facts = [dict(f) for f in raw if f["project"] == task.get("project") and f["version_scope"] == task.get("version_scope") and f["attribute"] in task.get("required", ["login_path", "auth_field"])]
    if backend == "latest":
        facts.sort(key=lambda f: (-f["created_step"], f["fact_id"]))
    else:
        facts = rank(task.get("query", "登录接口 认证字段"), facts, backend, encoder)
    context = {"checkpoint_id": cp, "status": "ok", "facts": [], "missing": [], "conflicts": [], "context_units": 0, "truncated": False, "mode": backend}
    for f in facts:
        cost = len(canonical(f).encode("utf-8"))
        if len(context["facts"]) >= top_k or context["context_units"] + cost > budget:
            context["truncated"] = True
            continue
        context["facts"].append(f)
        context["context_units"] += cost
    return context


def evaluate(out="output/evaluation-v020", semantic=False, split="test"):
    from .build_data import build
    if not (ROOT/"data/test/streams.jsonl").exists():
        build()
    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    streams = []
    for part in (["dev", "test"] if split == "all" else [split]):
        streams.extend(json.loads(line) for line in (ROOT/f"data/{part}/streams.jsonl").read_text(encoding="utf-8").splitlines())
    truths = {t["stream_id"]: t for t in (json.loads(line) for line in (ROOT/"evaluation/labels/truth.jsonl").read_text(encoding="utf-8").splitlines())}
    method_ids = list(METHODS) if semantic else ["B0", "B2", "B3"]
    load_start = time.perf_counter()
    encoder = BGEEncoder() if semantic else None
    model_load_seconds = round(time.perf_counter()-load_start, 4)
    # Freeze and save input/config hash before executing any probes.
    config = {"protocol": "synthetic-regression-v2", "context_policy": "governed representative evidence; baseline raw observations", "split": split, "methods": method_ids, "budget": 2048, "budget_unit": "UTF-8 bytes, conservative token upper bound", "top_k": 8, "generator": "deterministic-tool-planner-v1", "extractor": RuleExtractor.revision, "model": {"id": MODEL_ID, "revision": MODEL_REVISION} if semantic else None, "input_sha256": digest(streams), "seed": 42, "python": platform.python_version(), "platform": platform.platform(), "scoring": "independent mock specs; exact tool args; no feedback writes", "data_status": "developer-visible, self-authored synthetic fixtures; exploratory"}
    config["config_hash"] = digest(config)
    (target/"config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    rows, decision_rows, learn_rows = [], [], []
    beginning = time.perf_counter()
    for stream in streams:
        truth = truths[stream["stream_id"]]
        shared = {e["event_id"]: RuleExtractor().extract(e) for e in stream["events"]}
        for method in method_ids:
            guard = MemoryGuard(stream_id=stream["stream_id"], extractor=CachedExtractor(shared), encoder=encoder)
            raw = []
            for event in stream["events"]:
                start = time.perf_counter()
                write = guard.ingest(event)
                learning_ms = (time.perf_counter()-start)*1000
                if method == "B3":
                    expected = Counter(truth["update_actions"][str(event["step"])] if str(event["step"]) in truth["update_actions"] else truth["update_actions"][event["step"]])
                    actual = Counter(d["action"] for d in write["decisions"])
                    decision_rows.append({"stream_id": stream["stream_id"], "step": event["step"], "expected": dict(expected), "actual": dict(actual), "match": expected == actual})
                for candidate in shared[event["event_id"]][0]:
                    fid = stable_id("raw", [event["event_id"], candidate])
                    raw.append(dict(candidate, fact_id=fid, created_step=event["step"], text=event["text"], evidence=[{"event_id": event["event_id"], "step": event["step"], "span": candidate["evidence_span"], "source_id": event["source_id"], "text": event["text"]}]))
                learn_rows.append({"stream_id": stream["stream_id"], "method": method, "step": event["step"], "governed_ingest_ms": round(learning_ms, 4), "note": "audit mirror maintained for EVERY method; raw policies do not use governance decisions"})
                probes = [(p, "regular") for p in stream["probes"] if p["checkpoint"] == event["step"]] + [(p, "diagnostic") for p in stream.get("diagnostics", []) if p["checkpoint"] == event["step"]]
                for probe, kind in probes:
                    task = {k: v for k, v in probe["task"].items() if k != "category"}
                    cp = guard.snapshot()
                    before = guard.state()["state_hash"]
                    start = time.perf_counter()
                    embedding_before = encoder.forward_batches if encoder else 0
                    if method == "B0":
                        context = {"checkpoint_id": cp, "status": "ok", "facts": [], "context_units": 0}
                    elif method in {"B1", "B2", "A2"}:
                        backend = METHODS[method][1]
                        context = raw_context(raw, task, cp, backend, encoder, config["budget"], config["top_k"])
                    else:
                        scope = {"project": task.get("project"), "version_scope": task.get("version_scope"), "attributes": task.get("required", ["login_path", "auth_field"])}
                        context = guard.retrieve(task.get("query", ""), scope, token_budget=config["budget"], top_k=config["top_k"], mode=METHODS[method][1], scope_filter=method != "A1")
                    prediction = plan(task, context)
                    latency = (time.perf_counter()-start)*1000
                    # Labels first enter HERE, after the planner has returned.
                    answer = truth["answers" if kind == "regular" else "diagnostic_answers"][task["task_id"]]
                    execution = mock_api_call([answer["spec"]], prediction["tool_args"]) if prediction["status"] == "call" else {"ok": False, "code": "NOT_CALLED"}
                    after = guard.state()["state_hash"]
                    if before != after:
                        raise RuntimeError("Probe mutated memory")
                    stale = bool(prediction["tool_args"] and prediction["tool_args"].get(answer.get("changed_field")) in answer.get("retired_values", []))
                    rows.append({"stream_id": stream["stream_id"], "method": method, "kind": kind, "step": event["step"], "category": probe["task"].get("category", "adaptation"), "task_id": task["task_id"], "task": task, "checkpoint_id": cp, "answerable": answer["answerable"], "stale_eligible": answer.get("stale_eligible", False), "stale_misuse": stale, "success": answer["answerable"] and execution["ok"], "correct_clarify": not answer["answerable"] and prediction["status"] == "clarify", "wrong_strong_answer": not answer["answerable"] and prediction["status"] == "call", "excess_clarify": answer["answerable"] and prediction["status"] == "clarify", "prediction": prediction, "execution": execution, "context": context, "latency_ms": round(latency, 4), "state_hash_before": before, "state_hash_after": after, "token_usage": None, "generation_model_calls": 0, "embedding_forward_batches": (encoder.forward_batches if encoder else 0)-embedding_before, "embedding_cache": "shared across methods and streams; no claims of cold-start runtime"})
            guard.close()
        print(f"Evaluated {stream['stream_id']} ({len(method_ids)} methods)", flush=True)
    methods = []
    for method in method_ids:
        selected = [r for r in rows if r["method"] == method and r["kind"] == "regular"]
        per_stream = []
        for stream in streams:
            group = [r for r in selected if r["stream_id"] == stream["stream_id"]]
            positives = [r for r in group if r["answerable"]]
            per_stream.append({"stream_id": stream["stream_id"], "success": sum(r["success"] for r in positives), "answerable": len(positives), "success_rate": sum(r["success"] for r in positives)/max(1,len(positives))})
        anchors = [r for r in selected if r["category"] == "anchor"]
        lost = 0
        for stream in streams:
            seq = [r for r in anchors if r["stream_id"] == stream["stream_id"]]
            if seq and seq[0]["success"]:
                lost += sum(not r["success"] for r in seq[1:])
        diagnostic = [r for r in rows if r["method"] == method and r["kind"] == "diagnostic"]
        methods.append({"method": method, "label": METHODS[method][0], "backend": METHODS[method][1], "success": sum(r["success"] for r in selected), "answerable": sum(r["answerable"] for r in selected), "correct_clarify": sum(r["correct_clarify"] for r in selected), "unanswerable": sum(not r["answerable"] for r in selected), "wrong_strong_answer": sum(r["wrong_strong_answer"] for r in selected), "excess_clarify": sum(r["excess_clarify"] for r in selected), "stale_misuse": sum(r["stale_misuse"] for r in selected), "stale_eligible": sum(r["stale_eligible"] for r in selected), "anchor_success": sum(r["success"] for r in anchors), "anchor_total": len(anchors), "anchor_initial_success_later_failed": lost, "macro_stream_success": sum(p["success_rate"] for p in per_stream)/len(per_stream), "per_stream": per_stream, "adaptation_before_correct_clarify": sum(r["correct_clarify"] for r in diagnostic if not r["answerable"]), "adaptation_after_success": sum(r["success"] for r in diagnostic if r["answerable"]), "diagnostic_pairs": len(streams), "mean_probe_ms": round(sum(r["latency_ms"] for r in selected)/len(selected),4)})
    summary = {"note": "自编合成回归集；共享规则提取与确定性规划器。结果仅验证记忆策略，无盲测标注，不主张通用智能体或生成模型收益。", "stream_count": len(streams), "event_count": sum(len(s["events"]) for s in streams), "unique_task_count": len({digest({k:v for k,v in r['task'].items() if k != 'task_id'}) for r in rows if r["kind"] == "regular"}), "probe_executions_per_method": len(streams)*18, "diagnostic_executions_per_method": len(streams)*2, "total_executions": len(rows), "extractor": config["extractor"], "generator": config["generator"], "model": config["model"], "config_hash": config["config_hash"], "methods": methods, "updates_exact_event_match": sum(r["match"] for r in decision_rows), "updates_total_events": len(decision_rows), "model_load_seconds": model_load_seconds, "embedding_cache_texts": len(encoder.cache) if encoder else 0, "embedding_forward_batches": encoder.forward_batches if encoder else 0, "elapsed_seconds": round(time.perf_counter()-beginning,3)}
    for m in methods:
        m['negative_impact'] = summarize([r for r in rows if r['method'] == m['method'] and r['kind'] == 'regular'])
    summary['product_version'] = '0.2.0'
    summary['context_policy'] = 'governed retrieval keeps one representative evidence span per fact; full provenance remains in audit'
    for name, payload in (("raw.jsonl", rows), ("decisions.jsonl", decision_rows), ("learning.jsonl", learn_rows)):
        (target/name).write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in payload), encoding="utf-8")
    (target/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return summary
