"""Run the six-step workbench story with a real model and independent simulator."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.api_agent.mock_tool import mock_api_call
from memory_guard import MemoryGuard
from memory_guard.agent import run_agent
from memory_guard.demo import DEMO_EVENTS, demo_event
from memory_guard.impact import commit, fork, prepare
from memory_guard.llm import ChatPlanner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="output/day1-demo")
    parser.add_argument("--model", default="qwen3-0.6b-q8_0")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080/v1")
    args = parser.parse_args()
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=False)
    planner = ChatPlanner(args.model, args.base_url)
    (target / "config.json").write_text(json.dumps(planner.config(), ensure_ascii=False, indent=2), encoding="utf-8")
    memory = MemoryGuard()
    rows, updates = [], []
    try:
        with (target / "raw.jsonl").open("x", encoding="utf-8") as log:
            for index in range(len(DEMO_EVENTS)):
                proposal = prepare(memory, demo_event(memory, index))
                updates.append(dict(step=index + 1, preflight_generator="deterministic-tool-planner-v1",
                                    report=proposal.report,
                                    acknowledgement="scripted demo acknowledgement, not a human review"))
                commit(memory, proposal, acknowledge=True)
                if index not in (0, 2, 4, 5):
                    continue
                for version, path, field in (("v1", "/api/login", "api_key"), ("v2", "/auth/token", "access_token")):
                    task = dict(task_id=f"step-{index + 1}-{version}", project="Atlas", version_scope=version,
                                query=f"使用 Atlas {version} 的登录 API，请按已学文档生成调用。")
                    result = run_agent(memory, task, planner=planner)
                    # Specs enter after generation. No real business HTTP call occurs.
                    score = mock_api_call([dict(project="Atlas", version=version, path=path, auth_field=field)], result["tool_args"]) if result["status"] == "call" else dict(ok=False, code="NOT_CALLED")
                    row = dict(step=index + 1, task=task, prediction=result, execution=score)
                    rows.append(row)
                    log.write(json.dumps(row, ensure_ascii=False) + "\n")
                    log.flush()
                    print(json.dumps(dict(step=index + 1, version=version, status=result["status"],
                                          simulated_tool=score["code"]), ensure_ascii=False), flush=True)
        restored = fork(memory, 3)
        try:
            recovery = dict(checkpoint=3, independent=restored.state()["state_hash"] != memory.state()["state_hash"],
                            event_count=len(restored.state()["events"]), original_events=len(memory.state()["events"]))
        finally:
            restored.close()
        audit = memory.export()
        (target / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = dict(model_calls=len(rows), errors=sum(r["prediction"]["status"] == "error" for r in rows),
                       updates=updates, recovery=recovery,
                       note="Synthetic demonstration. Real model task planning, deterministic preflight, local mock API scoring.")
        (target / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1 if summary["errors"] else 0
    finally:
        memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
