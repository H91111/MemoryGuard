import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path

from memory_guard.server import create_server

ROOT = Path(__file__).resolve().parent.parent/'runtime/tests'
ROOT.mkdir(parents=True, exist_ok=True)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.server = create_server(str(Path(self.temp.name)/'server.db'), 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url+path, data=data, headers=headers if headers is not None else {'X-Memory-Guard':'local','Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def event(self):
        return dict(event_id='http-new', text='登录路径为 /changed。', project='Atlas', version_scope='v2', source_id='notes')

    def test_product_identity_and_scoped_state(self):
        self.assertEqual(self.request('/api/health')[1]['version'], '0.2.0')
        self.assertEqual(self.request('/api/state?checkpoint=4')[1]['step'], 4)
        self.assertEqual(self.request('/api/state?checkpoint=99')[0], 400)

    def test_preview_commit_gate_and_stale_token(self):
        _, report = self.request('/api/preview', {'event':self.event()})
        self.assertEqual(self.request('/api/state')[1]['step'], 6)
        self.assertEqual(self.request('/api/commit', {'preview_id':report['preview_id']})[0], 400)
        self.assertEqual(self.request('/api/commit', {'preview_id':report['preview_id'],'acknowledge':True})[0], 200)
        self.assertEqual(self.request('/api/commit', {'preview_id':report['preview_id'],'acknowledge':True})[0], 400)
        self.assertEqual(self.request('/api/task', {'task':{'project':'Atlas','version_scope':'v2'}})[1]['status'], 'clarify')

    def test_session_switch_invalidates_preview(self):
        _, report = self.request('/api/preview', {'event':self.event()})
        self.request('/api/new-session', {'name':'另一会话'})
        self.request('/api/switch-session', {'session_id':'initial'})
        self.assertEqual(self.request('/api/commit', {'preview_id':report['preview_id'],'acknowledge':True})[0], 400)

    def test_restore_export_import_roundtrip(self):
        _, source = self.request('/api/state?checkpoint=4')
        self.request('/api/restore', {'checkpoint':4})
        _, audit = self.request('/api/export')
        self.assertEqual(audit['state']['state_hash'], source['state_hash'])
        self.assertEqual(self.request('/api/import', {'audit':audit})[0], 200)
        self.assertEqual(self.request('/api/state')[1]['state_hash'], source['state_hash'])
        self.assertEqual(len(self.request('/api/sessions')[1]['sessions']), 3)

    def test_unknown_project_is_not_reported_as_tool_failure(self):
        self.request('/api/ingest', dict(event_id='orion', text='登录路径为 /login；认证字段为 token。', project='Orion', version_scope='v3', source_id='docs'))
        _, r = self.request('/api/task', {'task':{'project':'Orion','version_scope':'v3'}})
        self.assertEqual(r['status'], 'call')
        self.assertEqual(r['execution_result'], {'ok':None,'code':'SPEC_NOT_CONFIGURED'})

    def test_malformed_input_returns_json_error(self):
        for path, body in [('/api/task',{'task':[]}),('/api/task',{'task':{'required':'bad'}}),('/api/preview',{'event':None}),('/api/import',{'audit':{}}),('/api/restore',{'checkpoint':None}),('/api/switch-session',{'session_id':'../outside'})]:
            with self.subTest(path=path, body=body):
                self.assertEqual(self.request(path,body)[0], 400)

    def test_cross_origin_and_missing_header_rejected(self):
        self.assertEqual(self.request('/api/new-session', {}, headers={'Origin':'https://other.invalid','X-Memory-Guard':'local'})[0], 403)
        self.assertEqual(self.request('/api/new-session', {}, headers={})[0], 403)
        self.assertEqual(self.request('/api/state', headers={'Host':'other.invalid'})[0], 403)

    def test_impact_is_prefix_only(self):
        _, report = self.request('/api/impact?checkpoint=5')
        self.assertEqual(report['blocked'], 1)
        self.assertEqual(report['recovered'], 0)
        self.assertEqual(self.request('/api/impact')[1]['recovered'], 1)
