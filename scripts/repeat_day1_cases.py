"""Repeat a few saved failures at the frozen generation settings, outside totals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.api_agent.mock_tool import mock_api_call
from memory_guard.llm import ChatPlanner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("output/evaluation-day1"))
    args = parser.parse_args()
    root = args.results
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if json.loads((root / "progress.json").read_text())["status"] != "complete":
        raise ValueError("Wait for the original evaluation to complete")
    rows = [json.loads(line) for line in (root / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
    selected = []
    predicates = [lambda r: r["method"] == "governed" and r["prediction"]["status"] == "error",
                  lambda r: r["prediction"]["status"] == "call" and not r["success"],
                  lambda r: r["method"] == "latest" and r["category"] == "anchor" and r["stage"] == "duplicates_and_conflict"]
    for predicate in predicates:
        match = next((r for r in rows if predicate(r) and r not in selected), None)
        if match:
            selected.append(match)
    c = config["planner"]
    planner = ChatPlanner(c["model"], c["base_url"], temperature=c["temperature"], seed=c["seed"], max_tokens=c["max_tokens"])
    truths = {t["stream_id"]: t for t in (json.loads(line) for line in (root / "scoring-labels.jsonl").read_text(encoding="utf-8").splitlines())}
    repeats = []
    with (root / "repeats.jsonl").open("x", encoding="utf-8") as log:
        for row in selected:
            for repetition in (1, 2):
                result = planner(row["task"], row["context"])
                answer = truths[row["stream_id"]]["answers"][row["task"]["task_id"]]
                execution = mock_api_call([answer["spec"]], result["tool_args"]) if result["status"] == "call" else {"ok": False, "code": "NOT_CALLED"}
                repeated = dict(stream_id=row["stream_id"], method=row["method"], task=row["task"], context=row["context"],
                                repetition=repetition, prediction=result, execution=execution,
                                same_status_and_args=all(result[k] == row["prediction"][k] for k in ("status", "tool_args")),
                                success=bool(answer["answerable"] and execution["ok"]))
                repeats.append(repeated)
                log.write(json.dumps(repeated, ensure_ascii=False) + "\n")
                log.flush()
    summary = dict(config_hash=config["config_hash"], selected_cases=len(selected), model_calls=len(repeats),
                   unchanged=sum(r["same_status_and_args"] for r in repeats),
                   successes=sum(r["success"] for r in repeats), errors=sum(r["prediction"]["status"] == "error" for r in repeats),
                   note="Same frozen temperature/seed; selected failures repeated twice. Not independent samples, not added to original 216 executions, not a general variance estimate.")
    (root / "repeats-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
