"""Default deterministic tool planning, with an optional injected model planner.

The planner receives only public task and retrieved evidence. It has no mock-tool
specs, answer labels, event stream, or feedback-write channel.
"""
from __future__ import annotations

import time

from .schema import digest


def validate_task(task):
    if not isinstance(task, dict):
        raise ValueError('task 必须是对象')
    for key in ('project', 'version_scope', 'operation', 'query'):
        if key in task and task[key] is not None and not isinstance(task[key], str):
            raise ValueError(f'task.{key} 必须是文本')
    required = task.get('required', ['login_path', 'auth_field'])
    if not isinstance(required, list) or any(not isinstance(a, str) for a in required):
        raise ValueError('task.required 必须是字符串数组')
    if 'payload' in task and not isinstance(task['payload'], dict):
        raise ValueError('task.payload 必须是对象')


def plan(task, context):
    validate_task(task)
    result = {"task_id": task.get("task_id", "interactive"), "checkpoint_id": context["checkpoint_id"], "status": "clarify", "tool_args": None, "evidence_ids": [], "reason": "", "token_usage": None, "generator": "deterministic-tool-planner-v1"}
    if not task.get("project") or not task.get("version_scope"):
        result["reason"] = "请明确项目和版本"
        return result
    if task.get("operation", "login") != "login":
        result["reason"] = "当前模拟工具只支持 login 操作"
        return result
    if context["status"] == "clarify":
        result["reason"] = "存在未决冲突，请提供授权纠错" if context.get("conflicts") else "缺少适用事实或条件：" + ", ".join(context.get("missing") or ["evidence"])
        return result
    # The same first-ranked selection rule is used by governed and baseline policies.
    values = {}
    for f in context["facts"]:
        if f["attribute"] not in values:
            values[f["attribute"]] = f
    required = task.get("required", ["login_path", "auth_field"])
    missing = [a for a in required if a not in values]
    if missing:
        result["reason"] = "检索预算内缺少必要证据：" + ", ".join(missing)
        return result
    if not all(a in values for a in ("login_path", "auth_field")):
        result["reason"] = "登录工具需要路径与认证字段"
        return result
    args = {"project": task["project"], "version": task["version_scope"], "operation": "login", "path": values["login_path"]["value"], "auth_field": values["auth_field"]["value"], "payload": task.get("payload", {"username": "demo"})}
    for attr in ("timeout", "retries", "anonymous"):
        if attr in required:
            args[attr] = values[attr]["value"]
    result.update(status="call", tool_args=args, evidence_ids=[values[a]["fact_id"] for a in dict.fromkeys(["login_path", "auth_field", *required])], reason="根据当前检查点内的适用证据生成工具调用")
    return result


def run_agent(guard, task, *, checkpoint=None, mode="character", token_budget=2048, top_k=8, planner=None):
    validate_task(task)
    before = guard.state(checkpoint)["state_hash"]
    start = time.perf_counter()
    scope = {"project": task.get("project"), "version_scope": task.get("version_scope"), "attributes": task.get("required", ["login_path", "auth_field"]), "as_of": task.get("as_of")}
    context = guard.retrieve(task.get("query", "登录接口 认证字段"), scope, checkpoint, token_budget, top_k, mode)
    result = (planner or plan)(task, context)
    result["latency_ms"] = round((time.perf_counter()-start)*1000, 3)
    result["memory_state_hash"] = before
    result["context"] = context
    if before != guard.state(checkpoint)["state_hash"]:
        raise RuntimeError("探针改变了记忆状态")
    result["output_hash"] = digest({k: result[k] for k in ("status", "tool_args", "evidence_ids")})
    return result
