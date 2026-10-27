"""Loopback-only, dependency-free local workbench."""
from __future__ import annotations

import json
import mimetypes
import threading
import uuid
import time
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import MemoryGuard
from .agent import run_agent
from .demo import DEMO_EVENTS, demo_event, load_demo
from .impact import prepare, commit, history, fork, compare
from .workspace import Workspace
from .schema import digest
from examples.api_agent.mock_tool import mock_api_call

WEB = Path(__file__).parent / "web"
ROOT = Path.cwd()


def create_server(db_path="runtime/memory.db", port=8765, stream_id="default"):
    lock = threading.RLock()
    workspace = Workspace(db_path, stream_id)
    active = {"encoder": None}
    previews = {}
    impact_cache = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, status, payload, content_type="application/json; charset=utf-8", disposition=None):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            if disposition:
                self.send_header("Content-Disposition", disposition)
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            port = self.server.server_port
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self):
            if not self.valid_host():
                self.send(403, {"error": "仅允许本机工作台访问"})
                return
            parsed = urlparse(self.path)
            try:
                with lock:
                    m = workspace.guard
                    if parsed.path == "/api/state":
                        value = parse_qs(parsed.query).get("checkpoint", [None])[0]
                        state = m.state(int(value) if value is not None else None)
                        state["latest_step"] = m.state()["step"]
                        state["demo_total"] = len(DEMO_EVENTS)
                        state['session_id'] = workspace.data['active']
                        state['session_name'] = workspace._item(workspace.data['active'])['name']
                        state['product_version'] = '0.2.0'
                        state["model"] = {"extractor": m.extractor.revision, "semantic_loaded": active["encoder"] is not None, "generator": "deterministic-tool-planner-v1"}
                        self.send(200, state)
                    elif parsed.path == "/api/export":
                        self.send(200, m.export(), disposition='attachment; filename="memory-guard-audit.json"')
                    elif parsed.path == "/api/evaluation":
                        file = ROOT / "output/evaluation-v020/summary.json"
                        self.send(200, json.loads(file.read_text(encoding="utf-8")) if file.exists() else {"methods": [], "note": "尚未运行；使用 python -m memory_guard evaluate"})
                    elif parsed.path == '/api/sessions':
                        self.send(200, workspace.list())
                    elif parsed.path == '/api/health':
                        self.send(200, {'product': 'MemoryGuard', 'version': '0.2.0', 'workspace': digest(str(Path(db_path).resolve()))})
                    elif parsed.path == '/api/impact':
                        value = parse_qs(parsed.query).get('checkpoint', [None])[0]
                        cp = int(value) if value is not None else None
                        key = m.state(cp)['state_hash']
                        if key not in impact_cache:
                            if len(impact_cache) >= 8:
                                impact_cache.clear()
                            if m.state(cp)['step'] > 200:
                                raise ValueError('网页逐步巡检上限200个事件；请用 Python compare 选择两个检查点')
                            impact_cache[key] = history(m, cp)
                        self.send(200, impact_cache[key])
                    elif parsed.path in {"/", "/style.css", "/app.js", "/favicon.svg"}:
                        path = WEB / ("index.html" if parsed.path == "/" else parsed.path[1:])
                        mime = {".html": "text/html", ".css": "text/css", ".js": "application/javascript", '.svg':'image/svg+xml'}[path.suffix]
                        self.send(200, path.read_bytes(), mime + "; charset=utf-8")
                    else:
                        self.send(404, {"error": "路径不存在"})
            except (ValueError, TypeError, KeyError, RuntimeError, OSError, sqlite3.Error) as exc:
                self.send(400, {"error": str(exc)})

        def do_POST(self):
            port = self.server.server_port
            origin = self.headers.get("Origin")
            if not self.valid_host() or self.headers.get("X-Memory-Guard") != "local" or (origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}):
                self.send(403, {"error": "请求来源校验失败"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 10_000_000 if self.path == '/api/import' else 100000
                if not 0 < length <= limit:
                    raise ValueError(f"请求体须为1—{limit}字节")
                raw = json.loads(self.rfile.read(length))
                if not isinstance(raw, dict):
                    raise ValueError("请求体必须是JSON对象")
                with lock:
                    m = workspace.guard
                    if self.path == '/api/preview':
                        previews_copy = list(previews.items())
                        for key, (created, _, _) in previews_copy:
                            if time.monotonic()-created > 900:
                                previews.pop(key, None)
                        if len(previews) >= 32:
                            previews.pop(next(iter(previews)))
                        prepared = prepare(m, raw['event'])
                        token = uuid.uuid4().hex
                        previews[token] = (time.monotonic(), workspace.data['active'], prepared)
                        result = dict(prepared.report, preview_id=token)
                    elif self.path == '/api/commit':
                        token = raw.get('preview_id')
                        item = previews.get(token)
                        if not item or item[1] != workspace.data['active'] or time.monotonic()-item[0] > 900:
                            raise ValueError('预检已失效，请重新预检')
                        result = commit(m, item[2], acknowledge=raw.get('acknowledge', False))
                        previews.pop(token, None)
                    elif self.path == "/api/ingest":
                        result = m.ingest(raw)
                    elif self.path == "/api/correct":
                        result = m.correct(raw["target_id"], raw["event"])
                    elif self.path == "/api/demo-step":
                        result = m.ingest(demo_event(m, raw["index"]))
                    elif self.path == "/api/new-session":
                        result = workspace.create(raw.get('name', '空白工作区'), demo=raw.get('demo') is True)
                        previews.clear()
                    elif self.path == '/api/switch-session':
                        result = workspace.switch(raw['session_id'])
                        previews.clear()
                    elif self.path == '/api/restore':
                        cp = raw['checkpoint']
                        if type(cp) is not int:
                            raise ValueError('恢复检查点须是已有前缀整数')
                        m.state(cp)
                        result = workspace.create(raw.get('name', f'从检查点 {cp} 恢复'), checkpoint=cp)
                        previews.clear()
                    elif self.path == '/api/import':
                        result = workspace.create(raw.get('name', '导入的审计会话'), exported=raw['audit'])
                        previews.clear()
                    elif self.path == "/api/task":
                        mode = raw.get("mode", "character")
                        if mode in {"semantic", "hybrid"} and active["encoder"] is None:
                            from .candidates import BGEEncoder
                            active["encoder"] = BGEEncoder()
                        m.encoder = active["encoder"]
                        result = run_agent(m, raw["task"], checkpoint=raw.get("checkpoint"), mode=mode, token_budget=raw.get("token_budget", 2048))
                        # Tool executes AFTER planning; no specifications enter the planner.
                        if result["status"] == "call":
                            specs = [{"project": "Atlas", "version": "v1", "path": "/api/login", "auth_field": "api_key"}, {"project": "Atlas", "version": "v2", "path": "/auth/token", "auth_field": "access_token"}, {"project": "Beacon", "version": "v2", "path": "/session/create", "auth_field": "bearer"}]
                            known = any(s['project'] == result['tool_args']['project'] and s['version'] == result['tool_args']['version'] for s in specs)
                            result["execution_result"] = mock_api_call(specs, result["tool_args"]) if known else {'ok': None, 'code': 'SPEC_NOT_CONFIGURED'}
                            result["simulator_note"] = "模拟器仅预置 Atlas/Beacon 示例；自定义项目需配置独立规格"
                    else:
                        self.send(404, {"error": "路径不存在"})
                        return
                    self.send(200, result)
            except (ValueError, KeyError, TypeError, RuntimeError, OSError, sqlite3.Error) as exc:
                self.send(400, {"error": str(exc)})

    class LocalServer(ThreadingHTTPServer):
        def server_close(self):
            super().server_close()
            workspace.close()
    try:
        server = LocalServer(("127.0.0.1", port), Handler)
    except Exception:
        workspace.close()
        raise
    server.workspace = workspace
    return server


def serve(db_path="runtime/memory.db", port=8765, stream_id="default"):
    server = create_server(db_path, port, stream_id)
    print(f"Memory Guard: http://127.0.0.1:{port}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
