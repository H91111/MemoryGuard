"""Read-only counterfactual rehearsal for non-parametric lifelong adaptation.

Behavioral changes are signals, not ground-truth correctness judgments. A
conflict-induced refusal can be the correct response and still reduce availability.
"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass

from .agent import run_agent
from .schema import digest, normalize_event
from .store import MemoryGuard


def automatic_tasks(state):
    scopes = sorted({(f['project'], f['version_scope']) for f in state['facts']})
    if len(scopes) > 100:
        raise ValueError('自动巡检最多100个范围，请通过 Python 接口显式选择任务')
    return [dict(task_id=f'{p}/{v}/login', project=p, version_scope=v) for p, v in scopes]


def compare(before, after, tasks=None):
    """Compare checkpoints on fixed tasks; never call business tools or write feedback."""
    with before.lock, after.lock:
        a, b = before.state(), after.state()
        tasks = automatic_tasks(a) if tasks is None else copy.deepcopy(tasks)
        if not isinstance(tasks, list) or len(tasks) > 100 or any(not isinstance(t, dict) for t in tasks):
            raise ValueError('tasks 必须是最多100项的任务对象数组')
        rows = []
        for task in tasks:
            left, right = run_agent(before, task), run_agent(after, task)
            if left['status'] == 'call':
                outcome = 'blocked' if right['status'] != 'call' else 'retained' if left['tool_args'] == right['tool_args'] else 'changed'
            else:
                outcome = 'recovered' if right['status'] == 'call' else 'unavailable'
            compact = lambda r: {k: r[k] for k in ('status', 'tool_args', 'reason', 'evidence_ids')}
            rows.append(dict(task=task, outcome=outcome, before=compact(left), after=compact(right)))
        counts = Counter(r['outcome'] for r in rows)
        eligible = sum(r['before']['status'] == 'call' for r in rows)
        if before.state()['state_hash'] != a['state_hash'] or after.state()['state_hash'] != b['state_hash']:
            raise RuntimeError('巡检意外修改记忆')
        return dict(before_checkpoint=a['checkpoint_id'], after_checkpoint=b['checkpoint_id'],
                    tasks=rows, counts=dict(counts), tested=len(rows), eligible=eligible,
                    availability_loss_rate=counts['blocked']/eligible if eligible else None,
                    unchanged_rate=counts['retained']/eligible if eligible else None,
                    note='按固定登录任务比较行为；不是正确率。参数变化可能是必要适应，冲突澄清可能是正确防护。无可调用旧任务时比率为空。')


def fork(guard, checkpoint=None, path=':memory:'):
    """Create a verified, independent prefix branch, retaining the source history."""
    with guard.lock:
        exported = guard.export()
        state = guard.state(checkpoint)
        exported['state'] = state
        exported['events'] = [r for r in exported['events'] if r['step'] <= state['step']]
        return MemoryGuard.replay(exported, path)


@dataclass
class PreparedUpdate:
    base_hash: str
    event: dict
    candidates: list
    errors: list
    revision: str
    report: dict
    fingerprint: str = ''

    def signature(self):
        return digest([self.base_hash, self.event, self.candidates, self.errors, self.revision, self.report])


class FrozenExtractor:
    def __init__(self, candidates, errors, revision):
        self.candidates, self.errors, self.revision = candidates, errors, revision

    def extract(self, event):
        return copy.deepcopy(self.candidates), list(self.errors)


def prepare(guard, event, tasks=None):
    """Extract once, rehearse on a private copy, and bind commit to this exact state."""
    event = normalize_event(copy.deepcopy(event))
    with guard.lock:
        state = guard.state()
        # Respect stream and step validation before model inference.
        if event.get('stream_id', guard.stream_id) != guard.stream_id:
            raise ValueError('stream_id 不匹配')
        if event.get('step', state['step'] + 1) != state['step'] + 1:
            raise ValueError('预检事件必须是下一步')
        if any(e['event_id'] == event['event_id'] for e in state['events']):
            raise ValueError('预检需要新的 event_id；重传已保存事件请使用 ingest')
        candidates, errors = guard.extractor.extract(event)
        candidate = fork(guard)
        try:
            candidate.extractor = FrozenExtractor(candidates, errors, guard.extractor.revision)
            write = candidate.ingest(event)
            report = compare(guard, candidate, tasks)
            after = candidate.state()
            old_conflicts = {f['fact_id'] for f in state['facts'] if f['status'] == 'conflict'}
            report['new_conflicts'] = [f['fact_id'] for f in after['facts'] if f['status'] == 'conflict' and f['fact_id'] not in old_conflicts]
            report['decisions'] = write['decisions']
            report['pending'] = sum(d['action'] == 'pending' for d in write['decisions'])
            report['requires_acknowledgement'] = bool(report['new_conflicts'] or report['pending'] or report['counts'].get('blocked') or report['counts'].get('changed'))
            report['risk'] = 'review' if report['requires_acknowledgement'] else 'clear' if report['eligible'] else 'uncovered'
            report['after_hash'] = after['state_hash']
            prepared = PreparedUpdate(state['state_hash'], event, candidates, errors, guard.extractor.revision, report)
            prepared.fingerprint = prepared.signature()
            return prepared
        finally:
            candidate.close()


def commit(guard, prepared, *, acknowledge=False):
    with guard.lock:
        if prepared.signature() != prepared.fingerprint:
            raise ValueError('预检内容已变化，请重新预检')
        if guard.state()['state_hash'] != prepared.base_hash:
            raise ValueError('记忆已被其他操作更新，请重新预检')
        if prepared.report['requires_acknowledgement'] and acknowledge is not True:
            raise ValueError('存在影响信号，请确认已查看风险后再保存')
        extractor = guard.extractor
        try:
            # Do not ask a stochastic model to re-extract at commit time.
            guard.extractor = FrozenExtractor(prepared.candidates, prepared.errors, prepared.revision)
            return guard.ingest(prepared.event)
        finally:
            guard.extractor = extractor


def history(guard, checkpoint=None):
    """Consecutive observed transitions; no future facts become earlier anchors."""
    with guard.lock:
        state = guard.state(checkpoint)
        rows = []
        for step in range(1, state['step'] + 1):
            left, right = fork(guard, step - 1), fork(guard, step)
            try:
                result = compare(left, right)
                result.update(step=step, event_id=state['events'][step-1]['event_id'])
                rows.append(result)
            finally:
                left.close()
                right.close()
        return dict(checkpoint_id=state['checkpoint_id'], transitions=rows,
                    blocked=sum(r['counts'].get('blocked', 0) for r in rows),
                    recovered=sum(r['counts'].get('recovered', 0) for r in rows),
                    changed=sum(r['counts'].get('changed', 0) for r in rows),
                    retained=sum(r['counts'].get('retained', 0) for r in rows),
                    note='统计为相邻学习步骤的任务次数，同一任务可能重复计数；不等于独立样本数。')
