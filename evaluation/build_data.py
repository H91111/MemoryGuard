"""Generate disclosed synthetic regression streams and SEPARATE scoring labels.

These are program-authored fixtures, not blind human-annotated research data.
The split is for reproducible integration checks, never a claim of independence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("MEMORY_GUARD_WORKSPACE", Path.cwd()))

SCENARIOS = [
    ("dev", "login-basic", "AtlasDev", "login_path", 7, False),
    ("dev", "auth-review", "BirchDev", "auth_field", 8, False),
    ("dev", "late-source", "CedarDev", "login_path", 7, True),
    ("dev", "auth-late", "DeltaDev", "auth_field", 8, True),
    ("test", "path-migration", "Aurora", "login_path", 7, True),
    ("test", "token-rename", "Boreal", "auth_field", 8, False),
    ("test", "untrusted-patch", "Cirrus", "auth_field", 7, True),
    ("test", "delayed-review", "Drift", "login_path", 8, False),
    ("test", "cross-project", "Ember", "login_path", 7, False),
    ("test", "negative-note", "Fjord", "auth_field", 8, True),
    ("test", "scoped-repair", "Grove", "login_path", 8, True),
    ("test", "conditional-note", "Harbor", "auth_field", 7, False),
]


def make_stream(split, name, project, changed, repair_step, late, ordinal):
    other = project + "Side"
    anchor_path, anchor_auth = f"/v1/{name}/session", "api_key"
    initial = {"login_path": f"/v2/{name}/session", "auth_field": "session_key"}
    revised = dict(initial)
    revised[changed] = f"/v2/{name}/token" if changed == "login_path" else "access_token"
    attr_zh = {"login_path": "登录路径", "auth_field": "认证字段"}
    events, labels, facts = [], {}, {}

    def event(n, version, values=None, *, who="docs", kind="observation", target_step=None, text=None, scoped=True):
        from memory_guard.extract import RuleExtractor
        from memory_guard.schema import stable_id
        e = {"event_id": f"{name}-{n:02d}", "step": n, "source_id": who, "observed_at": f"2026-01-{ordinal+1:02d}T08:{n:02d}:00Z", "text": text or f"{other if who == 'side-docs' else project} {version} " + "；".join(f"{attr_zh[k]}{'是' if n%2 else '为'} {v}" for k, v in values.items()) + "。"}
        if scoped:
            e.update(project=project if who != "side-docs" else other, version_scope=version)
        if kind == "correction":
            e.update(kind=kind, target_id=facts[target_step])
        events.append(e)
        cs, _ = RuleExtractor().extract(e)
        for c in cs:
            facts[n] = stable_id("fact", {k: v for k, v in c.items() if k != "evidence_span"} | {"event_id": e["event_id"]})
        return e

    event(1, "v1", {"login_path": anchor_path}); labels[1] = ["supplement"]
    event(2, "v1", {"auth_field": anchor_auth}); labels[2] = ["supplement"]
    event(3, "v2", {"login_path": initial["login_path"]}); labels[3] = ["coexist"]
    event(4, "v2", {"auth_field": initial["auth_field"]}); labels[4] = ["coexist"]
    event(5, "v2", {changed: initial[changed]}, who="team-notes"); labels[5] = ["duplicate"]
    event(6, "v2", {changed: revised[changed]}, who="unverified"); labels[6] = ["conflicts"]
    # Corrections explicitly target the original assertion, never a hidden answer ID.
    target = 3 if changed == "login_path" else 4
    if repair_step == 7:
        event(7, "v2", {changed: revised[changed]}, who="maintainer", kind="correction", target_step=target); labels[7] = ["supersedes"]
        event(8, "v2", {"login_path": "/side/session", "auth_field": "bearer"}, who="side-docs"); labels[8] = ["coexist", "coexist"]
    else:
        event(7, "v2", {changed: revised[changed]}, who="self-proclaimed-official", kind="correction", target_step=target); labels[7] = ["pending"]
        event(8, "v2", {changed: revised[changed]}, who="maintainer", kind="correction", target_step=target); labels[8] = ["supersedes"]
    if late:
        event(9, "v2", {changed: initial[changed]}, who="late-archive"); labels[9] = ["conflicts"]
        event(10, "v2", {changed: initial[changed]}, who="unknown", kind="correction", target_step=6); labels[10] = ["pending"]
        event(11, "v2", {changed: revised[changed]}, who="maintainer", kind="correction", target_step=9); labels[11] = ["supersedes"]
    else:
        event(9, "v1", {"login_path": anchor_path}, who="late-archive"); labels[9] = ["duplicate"]
        event(10, "v2", {changed: initial[changed]}, who="unknown", kind="correction", target_step=6); labels[10] = ["pending"]
        event(11, "v2", {changed: revised[changed]}, who="followup"); labels[11] = ["duplicate"]
    pending = "如果负载大于10，登录路径为 /conditional。" if ordinal%2 else "此接口不允许匿名访问；登录路径不能使用 /forbidden。"
    event(12, "v3", text=pending, scoped=bool(ordinal%2)); labels[12] = ["pending"]

    probes, answers, diagnostics = [], {}, []
    for cp in range(2, 13, 2):
        current_version = "v1" if cp == 2 else "v2"
        current_values = {"login_path": anchor_path, "auth_field": anchor_auth} if cp == 2 else initial if cp == 4 else revised
        conflict = cp == 6 or (late and cp == 10)
        tasks = [
            {"task_id": f"{name}-anchor-{cp}", "project": project, "version_scope": "v1", "query": "使用第一版登录接口及其认证字段，保留历史兼容", "category": "anchor"},
            {"task_id": f"{name}-current-{cp}", "project": project, "version_scope": current_version, "query": "当前版本登录地址与令牌字段是什么？", "category": "current"},
            {"task_id": f"{name}-boundary-{cp}", "project": other if cp in (6,8) else project, "version_scope": "v2" if cp in (6,8) else "v9", "query": "为另一适用范围发起登录", "category": "boundary"},
        ]
        for task in tasks:
            probes.append({"checkpoint": cp, "task": task})
            is_current = task["category"] == "current"
            answerable = task["category"] == "anchor" or (is_current and not conflict) or (task["category"] == "boundary" and cp == 8 and repair_step == 7)
            vals = {"login_path": anchor_path, "auth_field": anchor_auth} if task["category"] == "anchor" else current_values if is_current else {"login_path": "/side/session", "auth_field": "bearer"}
            spec = {"project": task["project"], "version": task["version_scope"], "path": vals["login_path"], "auth_field": vals["auth_field"]}
            answers[task["task_id"]] = {"answerable": answerable, "spec": spec, "stale_eligible": is_current and cp >= 6, "retired_values": [initial[changed]] if is_current and cp >= 6 else [], "changed_field": "path" if changed == "login_path" else "auth_field"}
    # Paired diagnosis immediately before and after the same explicit correction.
    dtask = {"task_id": name + "-adapt", "project": project, "version_scope": "v2", "query": "登录接口和认证字段"}
    for cp in (repair_step-1, repair_step):
        diagnostics.append({"checkpoint": cp, "task": dict(dtask, task_id=dtask["task_id"]+f"-{cp}")})
    diagnostic_answers = {d["task"]["task_id"]: {"answerable": d["checkpoint"] == repair_step, "spec": {"project": project, "version": "v2", "path": revised["login_path"], "auth_field": revised["auth_field"]}} for d in diagnostics}
    return {"stream_id": name, "split": split, "events": events, "probes": probes, "diagnostics": diagnostics}, {"stream_id": name, "answers": answers, "diagnostic_answers": diagnostic_answers, "update_actions": labels}


def build():
    streams, labels = [], []
    for n, scenario in enumerate(SCENARIOS):
        stream, truth = make_stream(*scenario, ordinal=n)
        streams.append(stream)
        labels.append(truth)
    for folder in ("data/dev", "data/test", "evaluation/labels"):
        (ROOT/folder).mkdir(parents=True, exist_ok=True)
    for split in ("dev", "test"):
        (ROOT/f"data/{split}/streams.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False)+"\n" for s in streams if s["split"] == split), encoding="utf-8")
    (ROOT/"evaluation/labels/truth.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False)+"\n" for x in labels), encoding="utf-8")
    print("Built 12 disclosed synthetic streams / 144 events / 216 regular probes")


if __name__ == "__main__":
    build()
