from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

RULE_VERSION = "scope-evidence-v1"
EXTRACTOR_REVISION = "conservative-zh-v1"
ATTRIBUTES = {"login_path", "auth_field", "timeout", "retries", "anonymous"}
LABELS = {"login_path": "登录路径", "auth_field": "认证字段", "timeout": "超时", "retries": "重试次数", "anonymous": "匿名访问"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def stable_id(prefix, value):
    return prefix + "_" + digest(value)[:20]


def now():
    return datetime.now(timezone.utc).isoformat()


def instant(value):
    if not isinstance(value, str):
        raise ValueError("时间必须为 ISO 8601 字符串")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("无效时间，使用 YYYY-MM-DD 或 ISO 8601") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_interval(start, end):
    if start:
        instant(start)
    if end:
        instant(end)
    if start and end and instant(start) >= instant(end):
        raise ValueError("valid_to 必须晚于 valid_from")


def overlaps(a, b):
    return not ((a.get("valid_to") and b.get("valid_from") and instant(a["valid_to"]) <= instant(b["valid_from"])) or
                (b.get("valid_to") and a.get("valid_from") and instant(b["valid_to"]) <= instant(a["valid_from"])))


def applicable(fact, at):
    if not at:
        return True
    dt = instant(at)
    return (not fact.get("valid_from") or instant(fact["valid_from"]) <= dt) and (not fact.get("valid_to") or dt < instant(fact["valid_to"]))


def normalize_event(raw):
    if not isinstance(raw, dict):
        raise ValueError("事件必须是 JSON 对象")
    if "authorized" in raw or "trusted" in raw:
        raise ValueError("授权由本地来源策略决定，事件不能自行声明 trusted/authorized")
    event = dict(raw)
    for name in ("event_id", "text", "source_id"):
        if not isinstance(event.get(name), str) or not event[name].strip():
            raise ValueError(f"{name} 是必填非空文本")
    if len(event["text"]) > 16000:
        raise ValueError("原文超过 16000 字符；请按独立事实拆分，不会静默截断")
    if len(event["event_id"]) > 200 or len(event["source_id"]) > 200:
        raise ValueError("标识符不得超过 200 字符")
    for key in ("project", "version_scope"):
        if event.get(key) is not None and (not isinstance(event[key], str) or len(event[key]) > 120):
            raise ValueError(f"{key} 必须是最多120字符的字符串")
    event.setdefault("kind", "observation")
    if not isinstance(event["kind"], str) or event["kind"] not in {"observation", "correction"}:
        raise ValueError("kind 必须是 observation 或 correction")
    event.setdefault("observed_at", now())
    instant(event["observed_at"])
    validate_interval(event.get("valid_from"), event.get("valid_to"))
    return event
