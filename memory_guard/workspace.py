"""Durable local sessions and safe imports. Paths never come from HTTP clients."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from .demo import load_demo
from .impact import fork
from .schema import now
from .store import MemoryGuard


class Workspace:
    def __init__(self, db_path, stream_id='default'):
        self.initial = Path(db_path).resolve()
        self.initial.parent.mkdir(parents=True, exist_ok=True)
        self.registry = self.initial.with_suffix('.workspace.json')
        self.stream_id = stream_id
        self.guard = None
        if self.registry.exists():
            self.data = json.loads(self.registry.read_text(encoding='utf-8'))
            item = self._item(self.data['active'])
            self.guard = self._open(item)
        else:
            existed = self.initial.exists()
            self.guard = MemoryGuard(str(self.initial), stream_id=stream_id)
            if not existed:
                load_demo(self.guard)
            item = dict(id='initial', file=self.initial.name, name='六步演示' if not existed else '原有工作区', created_at=now())
            self.data = dict(active=item['id'], sessions=[item])
            self._save()

    def _item(self, session_id):
        item = next((s for s in self.data['sessions'] if s['id'] == session_id), None)
        if item is None:
            raise ValueError('会话不存在')
        return item

    def _path(self, item):
        path = self.initial.parent / item['file']
        if path.resolve().parent != self.initial.parent or path.suffix != '.db':
            raise ValueError('会话路径无效')
        return path

    def _open(self, item):
        path = self._path(item)
        if not path.is_file():
            raise ValueError('会话数据库缺失，请从审计包恢复')
        return MemoryGuard(str(path), stream_id=self.stream_id)

    def _save(self):
        temp = self.registry.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, self.registry)

    def list(self):
        return dict(active=self.data['active'], sessions=[dict(s) for s in self.data['sessions']])

    def switch(self, session_id):
        if session_id == self.data['active']:
            return self.list()
        guard = self._open(self._item(session_id))
        old_active = self.data['active']
        self.data['active'] = session_id
        try:
            self._save()
        except Exception:
            self.data['active'] = old_active
            guard.close()
            raise
        self.guard.close()
        self.guard = guard
        return self.list()

    def create(self, name='空白工作区', *, demo=False, checkpoint=None, exported=None):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('会话名称须为1—80字符')
        sid = uuid.uuid4().hex
        item = dict(id=sid, file=f'session-{sid}.db', name=name.strip(), created_at=now())
        path = str(self._path(item))
        if exported is not None:
            if not isinstance(exported, dict) or exported.get('format') != 'memory-guard-export-v1':
                raise ValueError('请选择 Memory Guard 审计 JSON 包')
            policy = exported.get('policy', {})
            if policy.get('stream_id') != self.stream_id or policy.get('trusted_sources') != ['maintainer']:
                raise ValueError('导入包来源策略与当前工作区不同；请使用 Python 接口显式配置')
            guard = MemoryGuard.replay(exported, path)
        elif checkpoint is not None:
            guard = fork(self.guard, checkpoint, path)
        else:
            guard = MemoryGuard(path, stream_id=self.stream_id)
            if demo:
                load_demo(guard)
        old_active = self.data['active']
        self.data['sessions'].append(item)
        self.data['active'] = sid
        try:
            self._save()
        except Exception:
            self.data['sessions'].pop()
            self.data['active'] = old_active
            guard.close()
            raise
        self.guard.close()
        self.guard = guard
        return self.list()

    def close(self):
        if self.guard:
            self.guard.close()
