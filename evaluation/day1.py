"""Same-planner day-one comparison, with labels confined to post-call scoring."""
from __future__ import annotations

import argparse
import copy
import json
import platform
import time
from pathlib import Path

from examples.api_agent.mock_tool import mock_api_call
from memory_guard import MemoryGuard
from memory_guard.extract import RuleExtractor
from memory_guard.schema import canonical, digest, stable_id

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("no_memory", "latest", "governed")
REQUIRED = ["login_path", "auth_field"]


def project_fact(fact):
    """Every policy pays for exactly this same fact representation."""
    evidence = fact.get("evidence", [])
    return {"fact_id": fact["fact_id"], "project": fact["project"],
            "version_scope": fact["version_scope"], "attribute": fact["attribute"],
            "value": fact["value"], "created_step": fact["created_step"],
            "evidence": [{k: e[k] for k in ("event_id", "source_id", "span", "text")} for e in evidence[:1]],
            "evidence_count": len(evidence)}


def make_context(method, guard, raw, task, *, budget, top_k):
    cp = guard.snapshot()
    context = {"checkpoint_id": cp, "status": "ok", "facts": [], "missing": [],
               "conflicts": [], "context_units": 2, "truncated": False, "mode": method}
    required = task.get("required", REQUIRED)
    if method == "governed":
        # Governance detects conflicts before the common final context budget.
        full = guard.retrieve(task.get("query", ""), {"project": task.get("project"),
                              "version_scope": task.get("version_scope"), "attributes": required},
                              token_budget=100000, top_k=100)
        context.update(status=full["status"], missing=full["missing"], conflicts=full["conflicts"])
        facts = full["facts"]
    elif method == "latest":
        facts = sorted((f for f in raw if f["project"] == task.get("project") and
                        f["version_scope"] == task.get("version_scope") and f["attribute"] in required),
                       key=lambda f: (-f["created_step"], f["fact_id"]))
    else:
        facts = []
    for fact in facts:
        projected = project_fact(fact)
        # retrieve() already shortened evidence to one span; retain the true count.
        projected["evidence_count"] = fact.get("evidence_count", projected["evidence_count"])
        proposed = context["facts"] + [projected]
        units = len(canonical(proposed).encode("utf-8"))
        if len(proposed) > top_k or units > budget:
            context["truncated"] = True
            continue
        context["facts"] = proposed
        context["context_units"] = units
    context["missing"] = list(dict.fromkeys(context["missing"] + [a for a in required if not any(f["attribute"] == a for f in context["facts"])]))
    if context["missing"] or context["conflicts"]:
        context["status"] = "clarify"
    return context


def metric(count, total):
    return {"count": count, "total": total, "rate": count / total if total else None}


def summarize(rows):
    previous, eligible, lost = {}, 0, 0
    pairs = []
    for row in rows:
        if row["category"] != "anchor":
            continue
        key = (row["stream_id"], row["task_key"])
        prior = previous.get(key)
        if (prior and prior["answerable"] and row["answerable"]
                and prior["task_hash"] == row["task_hash"]
                and prior["answer_hash"] == row["answer_hash"] and prior["success"]):
            eligible += 1
            lost += not row["success"]
            pairs.append({"stream_id": row["stream_id"], "task_key": row["task_key"], "before_step": prior["step"],
                          "after_step": row["step"], "task_hash": row["task_hash"],
                          "answer_hash": row["answer_hash"], "regressed": not row["success"]})
        previous[key] = row
    answerable = [r for r in rows if r["answerable"]]
    new = [r for r in answerable if r["category"] == "new"]
    calls = [r for r in rows if r["prediction"]["status"] == "call"]
    unanswerable = [r for r in rows if not r["answerable"]]
    return {"executions": len(rows), "generation_model_calls": sum(r["prediction"].get("generation_model_calls", 0) for r in rows),
            "token_usage": {k: sum((r["prediction"].get("token_usage") or {}).get(k, 0) for r in rows)
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "success": metric(sum(r["success"] for r in answerable), len(answerable)),
            "new_task_success": metric(sum(r["success"] for r in new), len(new)),
            "old_task_regression": metric(lost, eligible), "old_task_pairs": pairs,
            "wrong_call": metric(sum(not r["success"] for r in calls), len(rows)),
            "wrong_call_among_calls": metric(sum(not r["success"] for r in calls), len(calls)),
            "excess_clarify": metric(sum(r["prediction"]["status"] == "clarify" for r in answerable), len(answerable)),
            "correct_clarify": metric(sum(r["prediction"]["status"] == "clarify" for r in unanswerable), len(unanswerable)),
            "planner_errors": sum(r["prediction"]["status"] == "error" for r in rows),
            "per_stage": [{"stage": stage, "success": sum(r["success"] for r in rows if r["stage"] == stage and r["answerable"]),
                           "answerable": sum(r["answerable"] for r in rows if r["stage"] == stage)}
                          for stage in dict.fromkeys(r["stage"] for r in rows)]}


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate(planner, out, split="acceptance", *, budget=2048, top_k=8, planner_config=None, limit_streams=None):
    if split not in {"dev", "acceptance"}:
        raise ValueError("split must be dev or acceptance")
    if type(budget) is not int or budget < 2 or type(top_k) is not int or top_k < 1:
        raise ValueError("budget must be at least 2 bytes; top_k must be a positive integer")
    if limit_streams is not None and (type(limit_streams) is not int or limit_streams < 1):
        raise ValueError("limit_streams must be a positive integer")
    streams = [json.loads(line) for line in (ROOT / "data" / "day1" / split / "streams.jsonl").read_text(encoding="utf-8").splitlines()]
    if limit_streams is not None:
        streams = streams[:limit_streams]
    truths = {t["stream_id"]: t for t in (json.loads(line) for line in (ROOT / "evaluation" / "labels" / f"day1-{split}.jsonl").read_text(encoding="utf-8").splitlines())}
    target = Path(out)
    target.mkdir(parents=True, exist_ok=False)
    config = {"protocol": "day1-same-planner-v1", "split": split, "methods": list(METHODS),
              "budget": budget, "top_k": top_k, "budget_unit": "UTF-8 bytes of canonical JSON facts array; task and shared prompt are outside this evidence budget",
              "planner": planner_config or {"name": getattr(planner, "__name__", type(planner).__name__)},
              "input_sha256": digest(streams), "scoring_sha256": digest([truths[s["stream_id"]] for s in streams]),
              "stream_count": len(streams), "planned_executions": sum(len(s["probes"]) for s in streams) * len(METHODS),
              "python": platform.python_version(), "extractor": RuleExtractor.revision,
              "data_status": "developer-visible self-authored synthetic fixtures; dev and acceptance names disjoint; not blind or external-user validation",
              "context_policy": "same fact projection and byte accounting; latest retains raw observations; governed merges duplicates and resolves authorized corrections",
              "preflight": "not evaluated here; current impact.py remains deterministic; these results compare full memory policies"}
    config["config_hash"] = digest(config)
    _write(target / "config.json", config)
    (target / "streams.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in streams), encoding="utf-8")
    (target / "scoring-labels.jsonl").write_text("".join(json.dumps(truths[s["stream_id"]], ensure_ascii=False) + "\n" for s in streams), encoding="utf-8")
    rows = []
    started = time.perf_counter()
    _write(target / "progress.json", {"status": "running", "completed": 0, "planned": config["planned_executions"]})
    with (target / "raw.jsonl").open("x", encoding="utf-8") as log:
        try:
            for stream in streams:
                for method in METHODS:
                    guard, raw = MemoryGuard(stream_id=stream["stream_id"]), []
                    try:
                        for event in stream["events"]:
                            guard.ingest(event)
                            candidates, _ = RuleExtractor().extract(event)
                            for candidate in candidates:
                                raw.append(dict(candidate, fact_id=stable_id("raw", [event["event_id"], candidate]),
                                                created_step=event["step"], evidence=[{"event_id": event["event_id"],
                                                "source_id": event["source_id"], "span": candidate["evidence_span"], "text": event["text"]}]))
                            for probe in (p for p in stream["probes"] if p["checkpoint"] == event["step"]):
                                task = copy.deepcopy(probe["task"])
                                context = make_context(method, guard, raw, task, budget=budget, top_k=top_k)
                                before = guard.state()["state_hash"]
                                begin_call = time.perf_counter()
                                try:
                                    prediction = planner(copy.deepcopy(task), copy.deepcopy(context))
                                    if not isinstance(prediction, dict) or prediction.get("status") not in {"call", "clarify", "error"}:
                                        raise ValueError("planner returned invalid status or non-object")
                                except Exception as exc:
                                    prediction = {"status": "error", "tool_args": None, "evidence_ids": [],
                                                  "reason": f"{type(exc).__name__}: {exc}"}
                                elapsed = round((time.perf_counter() - begin_call) * 1000, 3)
                                after = guard.state()["state_hash"]
                                if after != before:
                                    raise RuntimeError("planner probe changed memory")
                                # Scoring answers enter only after the planner returns.
                                answer = truths[stream["stream_id"]]["answers"][task["task_id"]]
                                execution = mock_api_call([answer["spec"]], prediction.get("tool_args")) if prediction["status"] == "call" else {"ok": False, "code": "NOT_CALLED"}
                                row = {"stream_id": stream["stream_id"], "method": method, "step": event["step"],
                                       "stage": probe["stage"], "category": probe["category"], "task_key": probe["task_key"],
                                       "task": task, "task_hash": digest({k: v for k, v in task.items() if k != "task_id"}),
                                       "context": context, "prediction": prediction, "execution": execution,
                                       "answerable": answer["answerable"], "answer_hash": digest(answer["spec"]),
                                       "success": bool(answer["answerable"] and execution["ok"]), "latency_ms": elapsed,
                                       "state_hash_before": before, "state_hash_after": after}
                                log.write(json.dumps(row, ensure_ascii=False) + "\n")
                                log.flush()
                                rows.append(row)
                                _write(target / "progress.json", {"status": "running", "completed": len(rows), "planned": config["planned_executions"]})
                    finally:
                        guard.close()
        except BaseException:
            _write(target / "progress.json", {"status": "interrupted", "completed": len(rows), "planned": config["planned_executions"]})
            raise
    result = {"protocol": config["protocol"], "config_hash": config["config_hash"], "total_executions": len(rows),
              "stream_count": len(streams), "planner": config["planner"], "elapsed_seconds": round(time.perf_counter() - started, 3),
              "generation_model_calls": sum(r["prediction"].get("generation_model_calls", 0) for r in rows),
              "note": "Developer-visible synthetic comparison scored by local mock API; no business API requests. Planner errors remain failures. Zero eligible old-task pairs has null rate.",
              "methods": {method: summarize([r for r in rows if r["method"] == method]) for method in METHODS}}
    _write(target / "summary.json", result)
    _write(target / "progress.json", {"status": "complete", "completed": len(rows), "planned": config["planned_executions"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--split", choices=["dev", "acceptance"], default="dev")
    parser.add_argument("--limit-streams", type=int)
    parser.add_argument("--budget", type=int, default=2048)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--model", default="qwen3-0.6b-q8_0")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080/v1")
    parser.add_argument("--model-manifest", type=Path,
                        help="Explicit JSON model provenance, snapshotted into the hashed run config")
    parser.add_argument("--runtime-manifest", type=Path,
                        help="Explicit JSON inference-runtime provenance, snapshotted into the hashed run config")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--deterministic-smoke", action="store_true",
                        help="Pipeline check only; never evidence of real AI execution")
    args = parser.parse_args()
    if args.deterministic_smoke:
        from memory_guard.agent import plan
        planner, config = plan, {"name": "deterministic-tool-planner-v1", "real_model": False}
    else:
        from memory_guard.llm import ChatPlanner
        planner = ChatPlanner(args.model, args.base_url, temperature=args.temperature, seed=args.seed,
                              max_tokens=args.max_tokens, timeout=args.timeout)
        config = planner.config()
    for option, key in ((args.model_manifest, "model_artifact"), (args.runtime_manifest, "runtime_artifact")):
        if option is not None:
            try:
                artifact = json.loads(option.read_text(encoding="utf-8-sig"))
                if not isinstance(artifact, dict):
                    raise ValueError("manifest must contain a JSON object")
            except (OSError, ValueError) as exc:
                parser.error(f"cannot read {option}: {exc}")
            config[key] = artifact
    print(json.dumps(evaluate(planner, args.out, args.split, budget=args.budget, top_k=args.top_k,
                              limit_streams=args.limit_streams, planner_config=config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
