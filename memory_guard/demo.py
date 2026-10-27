from __future__ import annotations

DEMO_EVENTS = [
    {"event_id": "demo-01", "text": "Atlas v1 登录路径为 /api/login；认证字段为 api_key。", "project": "Atlas", "version_scope": "v1", "source_id": "docs-v1"},
    {"event_id": "demo-02", "text": "Atlas v1 登录接口是 /api/login。", "project": "Atlas", "version_scope": "v1", "source_id": "team-notes"},
    {"event_id": "demo-03", "text": "Atlas v2 登录路径为 /auth/token；认证字段为 access_token。", "project": "Atlas", "version_scope": "v2", "source_id": "docs-v2"},
    {"event_id": "demo-04", "text": "Beacon v2 登录路径为 /session/create；认证字段为 bearer。", "project": "Beacon", "version_scope": "v2", "source_id": "beacon-docs"},
    {"event_id": "demo-05", "text": "Atlas v2 登录路径为 /legacy/login。", "project": "Atlas", "version_scope": "v2", "source_id": "unverified-note"},
    {"event_id": "demo-06", "text": "Atlas v2 登录路径为 /auth/token；修正此前错误记录。", "project": "Atlas", "version_scope": "v2", "source_id": "maintainer", "kind": "correction"},
]


def demo_event(guard, index):
    if type(index) is not int or not 0 <= index < len(DEMO_EVENTS):
        raise ValueError("演示步骤超出范围")
    e = dict(DEMO_EVENTS[index], observed_at=f"2026-10-24T10:{index:02d}:00Z")
    if e.get("kind") == "correction":
        targets = [f for f in guard.state()["facts"] if f["project"] == "Atlas" and f["version_scope"] == "v2" and f["value"] == "/legacy/login" and f["status"] != "superseded"]
        if len(targets) != 1:
            raise ValueError("请先写入冲突事件，再演示定向纠错")
        e["target_id"] = targets[0]["fact_id"]
    return e


def load_demo(guard):
    results = []
    for i in range(len(DEMO_EVENTS)):
        if any(e["event_id"] == DEMO_EVENTS[i]["event_id"] for e in guard.state()["events"]):
            continue
        results.append(guard.ingest(demo_event(guard, i)))
    return results
