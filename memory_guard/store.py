from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .candidates import rank
from .extract import RuleExtractor
from .schema import RULE_VERSION, applicable, canonical, digest, normalize_event, overlaps, stable_id, instant


class MemoryGuard:
    """Append-only SQLite memory. One store is one independently reset stream.

    A checkpoint is an observed event prefix, never an effective-time timestamp.
    Source permissions are constructor configuration, not writable event content.
    """

    def __init__(self, path=":memory:", *, stream_id="default", trusted_sources=("maintainer",), extractor=None, encoder=None):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.stream_id = stream_id
        self.trusted_sources = frozenset(trusted_sources)
        self.extractor = extractor or RuleExtractor()
        self.encoder = encoder
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(step INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL,
          input_hash TEXT NOT NULL, payload TEXT NOT NULL, extractor_revision TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS facts(fact_id TEXT PRIMARY KEY, created_step INTEGER NOT NULL,
          payload TEXT NOT NULL, FOREIGN KEY(created_step) REFERENCES events(step));
        CREATE TABLE IF NOT EXISTS evidence(fact_id TEXT NOT NULL, event_id TEXT NOT NULL,
          step INTEGER NOT NULL, span TEXT NOT NULL, UNIQUE(fact_id,event_id,span),
          FOREIGN KEY(fact_id) REFERENCES facts(fact_id), FOREIGN KEY(event_id) REFERENCES events(event_id));
        CREATE TABLE IF NOT EXISTS relations(relation_id TEXT PRIMARY KEY, step INTEGER NOT NULL,
          left_id TEXT NOT NULL, right_id TEXT NOT NULL, relation TEXT NOT NULL, basis_event_id TEXT NOT NULL,
          FOREIGN KEY(left_id) REFERENCES facts(fact_id), FOREIGN KEY(right_id) REFERENCES facts(fact_id));
        CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY, step INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS evidence_step ON evidence(step);
        """)
        policy = canonical({"stream_id": stream_id, "trusted_sources": sorted(self.trusted_sources), "rule_version": RULE_VERSION})
        old = self.db.execute("SELECT value FROM meta WHERE key='policy'").fetchone()
        if old and old[0] != policy:
            self.db.close()
            raise ValueError("数据库的 stream/source/rule 策略与当前配置不同；请使用原配置或新数据库")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('policy',?)", (policy,))
        self.db.commit()

    def close(self):
        self.db.close()

    def _step(self, checkpoint=None):
        latest = self.db.execute("SELECT COALESCE(MAX(step),0) FROM events").fetchone()[0]
        if checkpoint is None:
            return latest
        if isinstance(checkpoint, str) and checkpoint.startswith("cp_"):
            try:
                _, n, hash_part = checkpoint.split("_")
                step = int(n)
            except (ValueError, TypeError) as exc:
                raise ValueError("检查点格式无效") from exc
            if step < 0 or step > latest or self._checkpoint(step) != checkpoint:
                raise ValueError("检查点不存在或不属于当前事件流")
            return step
        if type(checkpoint) is not int or not 0 <= checkpoint <= latest:
            raise ValueError("检查点必须是已有前缀的整数步或 cp 标识")
        return checkpoint

    def _checkpoint(self, step):
        rows = self.db.execute("SELECT event_id,input_hash,extractor_revision FROM events WHERE step<=? ORDER BY step", (step,)).fetchall()
        policy = json.loads(self.db.execute("SELECT value FROM meta WHERE key='policy'").fetchone()[0])
        signature = digest({'policy': policy, 'events': [list(r) for r in rows]})[:16]
        return f"cp_{step}_{signature}"

    def snapshot(self):
        with self.lock:
            return self._checkpoint(self._step())

    @staticmethod
    def _key(fact):
        return tuple(fact[k] for k in ("project", "version_scope", "subject", "attribute"))

    def _rows(self, step):
        facts = [dict(json.loads(r["payload"]), fact_id=r["fact_id"], created_step=r["created_step"]) for r in self.db.execute("SELECT * FROM facts WHERE created_step<=? ORDER BY created_step,fact_id", (step,))]
        events = {r["event_id"]: json.loads(r["payload"]) for r in self.db.execute("SELECT * FROM events WHERE step<=?", (step,))}
        for f in facts:
            f["evidence"] = [{"event_id": r["event_id"], "step": r["step"], "span": json.loads(r["span"]), "source_id": events[r["event_id"]]["source_id"], "text": events[r["event_id"]]["text"]} for r in self.db.execute("SELECT * FROM evidence WHERE fact_id=? AND step<=? ORDER BY step", (f["fact_id"], step))]
            f["text"] = f["evidence"][0]["text"]
        edges = [dict(r) for r in self.db.execute("SELECT * FROM relations WHERE step<=? ORDER BY step,relation_id", (step,))]
        return facts, edges

    @staticmethod
    def _active(facts, edges):
        hidden = {r["right_id"] for r in edges if r["relation"] == "supersedes"}
        return [f for f in facts if f["fact_id"] not in hidden]

    def _decide(self, step, event, action, reason, fact_ids=()):
        number = self.db.execute("SELECT COUNT(*) FROM decisions WHERE step=?", (step,)).fetchone()[0]
        data = {"decision_id": stable_id("decision", [event["event_id"], number]), "step": step, "event_id": event["event_id"], "action": action, "reason": reason, "input_ids": [event["event_id"], *fact_ids], "fact_ids": list(fact_ids), "rule_version": RULE_VERSION, "extractor_revision": self.extractor.revision}
        self.db.execute("INSERT INTO decisions VALUES(?,?,?)", (data["decision_id"], step, canonical(data)))

    def _relate(self, step, event_id, left, right, relation):
        if left == right:
            return
        rid = stable_id("relation", [event_id, left, right, relation])
        self.db.execute("INSERT OR IGNORE INTO relations VALUES(?,?,?,?,?,?)", (rid, step, left, right, relation, event_id))

    def ingest(self, raw):
        # Strip only the generated observed_at for idempotent retransmissions.
        input_hash = digest(raw)
        event = normalize_event(raw)
        if event.get("stream_id", self.stream_id) != self.stream_id:
            raise ValueError("stream_id 不匹配")
        with self.lock, self.db:
            old = self.db.execute("SELECT * FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
            if old:
                if old["input_hash"] != input_hash:
                    raise ValueError("event_id 已存在且内容不同；原始事件不可修改")
                return self._write_result(old["step"], idempotent=True)
            step = self._step() + 1
            if event.get("step", step) != step:
                raise ValueError("step 必须严格递增，不可插入过去或未来事件")
            event["step"], event["stream_id"] = step, self.stream_id
            self.db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (step, event["event_id"], input_hash, canonical(event), self.extractor.revision))
            candidates, errors = self.extractor.extract(event)
            if event["kind"] == "correction" and len(candidates) != 1:
                errors.append("定向纠错必须且只能包含一个事实")
                candidates = []
            for error in errors:
                self._decide(step, event, "pending", error)
            for c in candidates:
                before, edges = self._rows(step)
                active = self._active(before, edges)
                key = self._key(c)
                relevant = [f for f in active if self._key(f) == key and overlaps(f, c)]
                target = None
                if event["kind"] == "correction":
                    target = next((f for f in before if f["fact_id"] == event.get("target_id")), None)
                    if event["source_id"] not in self.trusted_sources:
                        self._decide(step, event, "pending", "来源未获本地策略授权，不能执行替代")
                        continue
                    if not target or self._key(target) != key or any(target.get(k) != c.get(k) for k in ("valid_from", "valid_to")):
                        self._decide(step, event, "pending", "纠错目标不存在或项目/版本/属性/有效时间不一致")
                        continue
                    if target not in active:
                        self._decide(step, event, "pending", "目标已被替代；请对当前断言纠错，避免建立替代环")
                        continue
                    if target["value"] == c["value"]:
                        self._decide(step, event, "pending", "纠错值与目标相同，不创建自我替代")
                        continue
                same = next((f for f in relevant if f["value"] == c["value"] and all(f.get(k) == c.get(k) for k in ("valid_from", "valid_to"))), None)
                fid = same["fact_id"] if same else stable_id("fact", {k: v for k, v in c.items() if k != "evidence_span"} | {"event_id": event["event_id"]})
                if not same:
                    self.db.execute("INSERT OR IGNORE INTO facts VALUES(?,?,?)", (fid, step, canonical(c)))
                self.db.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?,?)", (fid, event["event_id"], step, canonical(c["evidence_span"])))
                if target:
                    self._relate(step, event["event_id"], fid, target["fact_id"], "supersedes")
                    self._decide(step, event, "supersedes", "本地授权来源显式指定同范围断言，建立定向替代并保留历史", [fid, target["fact_id"]])
                elif same:
                    self._decide(step, event, "duplicate", "同范围、同值、同有效时间，关联原文证据，不新增逻辑事实", [fid])
                else:
                    conflicts = [f for f in relevant if f["value"] != c["value"]]
                    if conflicts:
                        for f in conflicts:
                            self._relate(step, event["event_id"], fid, f["fact_id"], "conflicts")
                        self._decide(step, event, "conflicts", "同范围同属性存在不同值，缺少授权替代依据；保留全部断言并澄清", [fid, *[f["fact_id"] for f in conflicts]])
                    else:
                        family = [f for f in active if f["subject"] == c["subject"] and f["attribute"] == c["attribute"]]
                        action = "coexist" if family else "supplement"
                        self._decide(step, event, action, "不同项目/版本/有效时间并存" if family else "新增独立属性事实", [fid])
            return self._write_result(step)

    def correct(self, target_id, correction_event):
        return self.ingest(dict(correction_event, kind="correction", target_id=target_id))

    def _write_result(self, step, idempotent=False):
        return {"checkpoint_id": self._checkpoint(step), "step": step, "idempotent": idempotent, "decisions": [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM decisions WHERE step=? ORDER BY decision_id", (step,))]}

    def retrieve(self, query="", scope=None, checkpoint=None, token_budget=2048, top_k=8, mode="character", *, scope_filter=True):
        if type(token_budget) is not int or not 1 <= token_budget <= 100000 or type(top_k) is not int or not 1 <= top_k <= 100:
            raise ValueError("token_budget 应为1—100000整数，top_k应为1—100整数")
        scope = scope or {}
        if not isinstance(scope, dict) or not isinstance(query, str):
            raise ValueError("scope 必须是对象，query 必须是文本")
        if mode not in {"character", "semantic", "hybrid"}:
            raise ValueError("未知检索模式")
        if scope.get("as_of"):
            instant(scope["as_of"])
        with self.lock:
            step = self._step(checkpoint)
            facts, edges = self._rows(step)
            result = {"checkpoint_id": self._checkpoint(step), "step": step, "status": "ok", "facts": [], "conflicts": [], "missing": [], "context_units": 0, "budget_unit": "UTF-8 bytes (conservative token upper bound)", "mode": mode, "truncated": False}
            for k in ("project", "version_scope"):
                if not isinstance(scope.get(k), str) or not scope[k].strip():
                    result["missing"].append(k)
            if result["missing"]:
                result["status"] = "clarify"
                return result
            scoped = [f for f in facts if (not scope_filter or all(f[k] == scope[k] for k in ("project", "version_scope"))) and f["subject"] == scope.get("subject", "api")]
            if not scope.get("as_of") and any(f.get("valid_from") or f.get("valid_to") for f in scoped):
                result.update(status="clarify", missing=["as_of"])
                return result
            visible = self._active([f for f in scoped if applicable(f, scope.get("as_of"))], edges)
            attributes = scope.get("attributes")
            if attributes is not None:
                if not isinstance(attributes, list) or any(not isinstance(a, str) for a in attributes):
                    raise ValueError("attributes 必须是字符串数组")
                visible = [f for f in visible if f["attribute"] in attributes]
                result["missing"] = [a for a in attributes if not any(f["attribute"] == a for f in visible)]
            groups = {}
            for f in visible:
                groups.setdefault(f["attribute"], []).append(f)
            for attr, group in groups.items():
                if len({f["value"] for f in group}) > 1:
                    result["conflicts"].append({"attribute": attr, "fact_ids": [f["fact_id"] for f in group], "values": sorted({f["value"] for f in group})})
            # Conflict detection precedes truncation: a tiny context cannot hide a conflict.
            ordered = rank(query, visible, mode, self.encoder)
            for f in ordered:
                # Keep all evidence in the audit store. Repeated observations must
                # not evict other required attributes from the task context.
                f = dict(f, evidence=f['evidence'][:1], evidence_count=len(f['evidence']))
                cost = len(canonical(f).encode("utf-8"))
                if len(result["facts"]) >= top_k or result["context_units"] + cost > token_budget:
                    result["truncated"] = True
                    continue
                result["facts"].append(f)
                result["context_units"] += cost
            if result["conflicts"] or result["missing"] or not result["facts"]:
                result["status"] = "clarify"
            return result

    def state(self, checkpoint=None):
        with self.lock:
            step = self._step(checkpoint)
            facts, edges = self._rows(step)
            active = {f["fact_id"] for f in self._active(facts, edges)}
            groups = {}
            for f in facts:
                if f["fact_id"] in active:
                    groups.setdefault(self._key(f), []).append(f)
            for f in facts:
                f["status"] = "superseded" if f["fact_id"] not in active else "conflict" if any(other["value"] != f["value"] and overlaps(f, other) for other in groups.get(self._key(f), [])) else "active"
            events = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM events WHERE step<=? ORDER BY step", (step,))]
            decisions = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM decisions WHERE step<=? ORDER BY step,decision_id", (step,))]
            state = {"stream_id": self.stream_id, "checkpoint_id": self._checkpoint(step), "step": step, "events": events, "facts": facts, "relations": edges, "decisions": decisions}
            state["state_hash"] = digest(state)
            return state

    def inspect(self, fact_id, checkpoint=None):
        state = self.state(checkpoint)
        fact = next((f for f in state["facts"] if f["fact_id"] == fact_id), None)
        if not fact:
            raise ValueError("当前检查点不存在该事实")
        return {"fact": fact, "relations": [r for r in state["relations"] if fact_id in (r["left_id"], r["right_id"])], "decisions": [d for d in state["decisions"] if fact_id in d["fact_ids"]], "checkpoint_id": state["checkpoint_id"]}

    def export(self):
        """Portable, immutable source log plus deterministic extraction cache."""
        with self.lock:
            rows = [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY step")]
            return {"format": "memory-guard-export-v1", "policy": json.loads(self.db.execute("SELECT value FROM meta WHERE key='policy'").fetchone()[0]), "events": rows, "state": self.state()}

    @classmethod
    def replay(cls, exported, path=":memory:"):
        if not isinstance(exported, dict) or exported.get('format') != 'memory-guard-export-v1':
            raise ValueError('审计包格式无效')
        policy = exported["policy"]
        if not isinstance(policy, dict) or not isinstance(exported.get('state'), dict) or not isinstance(exported.get('events'), list):
            raise ValueError('审计包结构无效')
        for key in ('facts', 'relations', 'decisions'):
            if not isinstance(exported['state'].get(key), list):
                raise ValueError('审计包记录结构无效')
        if policy.get('rule_version') != RULE_VERSION:
            raise ValueError('审计包规则版本不兼容')
        guard = cls(path, stream_id=policy["stream_id"], trusted_sources=policy["trusted_sources"])
        if guard._step():
            guard.close()
            raise ValueError("回放目标必须为空数据库")
        try:
            with guard.db:
                for r in exported["events"]:
                    guard.db.execute("INSERT INTO events VALUES(?,?,?,?,?)", tuple(r[k] for k in ("step", "event_id", "input_hash", "payload", "extractor_revision")))
                state = exported["state"]
                for f in state["facts"]:
                    payload = {k: f[k] for k in ("project", "version_scope", "subject", "attribute", "value", "evidence_span", "valid_from", "valid_to")}
                    guard.db.execute("INSERT INTO facts VALUES(?,?,?)", (f["fact_id"], f["created_step"], canonical(payload)))
                    for e in f["evidence"]:
                        guard.db.execute("INSERT INTO evidence VALUES(?,?,?,?)", (f["fact_id"], e["event_id"], e["step"], canonical(e["span"])))
                for r in state["relations"]:
                    guard.db.execute("INSERT INTO relations VALUES(?,?,?,?,?,?)", tuple(r[k] for k in ("relation_id", "step", "left_id", "right_id", "relation", "basis_event_id")))
                for d in state["decisions"]:
                    guard.db.execute("INSERT INTO decisions VALUES(?,?,?)", (d["decision_id"], d["step"], canonical(d)))
                if guard.state()["state_hash"] != state["state_hash"]:
                    raise ValueError("回放完整性校验失败")
        except Exception:
            guard.close()
            raise
        return guard
