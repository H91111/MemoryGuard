"""Build developer-visible day-one fixtures; scoring labels are separate files."""
from __future__ import annotations

import json
from pathlib import Path

from memory_guard.extract import RuleExtractor
from memory_guard.schema import stable_id

ROOT = Path(__file__).resolve().parents[1]


def make_stream(split, ordinal):
    name = f"day1-{split}-{ordinal + 1:02d}"
    project = f"{'Dev' if split == 'dev' else 'Acceptance'}API{ordinal + 1}"
    repeated = "login_path" if ordinal % 2 == 0 else "auth_field"
    changed = "auth_field" if ordinal % 3 == 0 else "login_path"
    label = {"login_path": "登录路径", "auth_field": "认证字段"}
    v1 = {"login_path": f"/v1/{project.lower()}/session", "auth_field": f"key_{ordinal + 1}"}
    v2 = {"login_path": f"/v2/{project.lower()}/session", "auth_field": f"token_{ordinal + 1}"}
    fixed = dict(v2)
    fixed[changed] = f"/v2/{project.lower()}/signin" if changed == "login_path" else f"bearer_{ordinal + 1}"
    events = []

    def event(version, values, *, source="docs", kind="observation", target=None):
        step = len(events) + 1
        result = {
            "event_id": f"{name}-event-{step:02d}", "step": step,
            "project": project, "version_scope": version, "source_id": source,
            "observed_at": f"2026-10-28T00:{ordinal:02d}:{step:02d}Z",
            "text": f"{project} {version} " + "；".join(f"{label[k]}为 {v}" for k, v in values.items()) + "。",
        }
        if kind == "correction":
            result.update(kind=kind, target_id=target)
        events.append(result)
        return result

    event("v1", v1)
    checkpoints = [dict(step=1, stage="learn_v1")]
    original_v2 = event("v2", v2)
    checkpoints.append(dict(step=2, stage="learn_v2"))
    for _ in range(10):
        event("v1", {repeated: v1[repeated]}, source="team-notes")
    event("v2", {changed: fixed[changed]}, source="unverified")
    checkpoints.append(dict(step=len(events), stage="duplicates_and_conflict"))
    candidate = next(c for c in RuleExtractor().extract(original_v2)[0] if c["attribute"] == changed)
    target = stable_id("fact", {k: v for k, v in candidate.items() if k != "evidence_span"} | {"event_id": original_v2["event_id"]})
    event("v2", {changed: fixed[changed]}, source="maintainer", kind="correction", target=target)
    checkpoints.append(dict(step=len(events), stage="authorized_correction"))
    probes, answers = [], {}
    for checkpoint in checkpoints:
        for category, version, query in (
            ("anchor", "v1", "保持第一版兼容，使用其登录接口与认证字段登录。"),
            ("new", "v2", "使用第二版 API 登录，填写文档要求的路径与认证字段。"),
            ("boundary", "v9", "使用第九版 API 登录；缺少适用证据时先澄清。"),
        ):
            task_id = f"{name}-{checkpoint['stage']}-{category}"
            task = {"task_id": task_id, "project": project, "version_scope": version,
                    "operation": "login", "query": query, "required": ["login_path", "auth_field"],
                    "payload": {"username": "demo"}}
            probes.append({"checkpoint": checkpoint["step"], "stage": checkpoint["stage"],
                           "category": category, "task_key": f"{name}/{category}", "task": task})
            answerable = category == "anchor" or (category == "new" and checkpoint["stage"] in {"learn_v2", "authorized_correction"})
            values = v1 if category == "anchor" else fixed if checkpoint["stage"] == "authorized_correction" else v2
            answers[task_id] = {"answerable": answerable, "spec": {"project": project, "version": version,
                                  "path": values["login_path"], "auth_field": values["auth_field"]}}
    return {"stream_id": name, "split": split, "events": events, "checkpoints": checkpoints, "probes": probes}, {"stream_id": name, "answers": answers}


def build():
    for split, count in (("dev", 2), ("acceptance", 6)):
        pairs = [make_stream(split, n) for n in range(count)]
        directory = ROOT / "data" / "day1" / split
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "streams.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s, _ in pairs), encoding="utf-8")
        labels = ROOT / "evaluation" / "labels"
        labels.mkdir(parents=True, exist_ok=True)
        (labels / f"day1-{split}.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for _, t in pairs), encoding="utf-8")


if __name__ == "__main__":
    build()
    print("Built 2 dev and 6 acceptance developer-visible synthetic streams; acceptance = 216 planner calls.")
