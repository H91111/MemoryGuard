import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_guard import MemoryGuard
from memory_guard.agent import run_agent
from memory_guard.demo import load_demo, demo_event
from memory_guard.impact import prepare, commit, fork, history
from memory_guard.workspace import Workspace

TEST_ROOT = Path(__file__).resolve().parent.parent / 'runtime' / 'tests'
TEST_ROOT.mkdir(parents=True, exist_ok=True)


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.m = MemoryGuard()
        for i in range(4):
            self.m.ingest(demo_event(self.m, i))

    def tearDown(self):
        self.m.close()

    def test_preview_readonly_and_conflict_blocks_only_target(self):
        state = self.m.state()
        p = prepare(self.m, demo_event(self.m, 4))
        self.assertEqual(state, self.m.state())
        self.assertEqual(p.report['counts'], {'retained': 2, 'blocked': 1})
        self.assertAlmostEqual(p.report['availability_loss_rate'], 1/3)
        with self.assertRaises(ValueError):
            commit(self.m, p)
        self.assertEqual(state, self.m.state())
        commit(self.m, p, acknowledge=True)
        self.assertEqual(self.m.state()['state_hash'], p.report['after_hash'])

    def test_stale_preview_cannot_overwrite_new_learning(self):
        p = prepare(self.m, demo_event(self.m, 4))
        self.m.ingest(dict(demo_event(self.m, 0), event_id='another'))
        before = self.m.state()
        with self.assertRaisesRegex(ValueError, '其他操作'):
            commit(self.m, p, acknowledge=True)
        self.assertEqual(before, self.m.state())

    def test_preview_tampering_rejected(self):
        p = prepare(self.m, demo_event(self.m, 4))
        p.event['text'] = '登录路径为 /tampered。'
        with self.assertRaisesRegex(ValueError, '内容已变化'):
            commit(self.m, p, acknowledge=True)

    def test_stochastic_extraction_not_repeated_on_commit(self):
        with patch.object(self.m.extractor, 'extract', wraps=self.m.extractor.extract) as mocked:
            p = prepare(self.m, demo_event(self.m, 4))
            commit(self.m, p, acknowledge=True)
            self.assertEqual(mocked.call_count, 1)

    def test_correction_recovers_not_false_regression(self):
        self.m.ingest(demo_event(self.m, 4))
        p = prepare(self.m, demo_event(self.m, 5))
        self.assertEqual(p.report['counts'], {'retained': 2, 'recovered': 1})
        commit(self.m, p)

    def test_parameter_change_is_review_not_claimed_error(self):
        target = next(f for f in self.m.state()['facts'] if f['project']=='Atlas' and f['version_scope']=='v2' and f['attribute']=='login_path')
        event = dict(event_id='change', project='Atlas', version_scope='v2', source_id='maintainer', kind='correction', target_id=target['fact_id'], text='登录路径为 /new。')
        p = prepare(self.m, event)
        self.assertEqual(p.report['counts']['changed'], 1)
        self.assertEqual(p.report['availability_loss_rate'], 0)
        self.assertTrue(p.report['requires_acknowledgement'])

    def test_no_baseline_is_null_not_perfect_retention(self):
        m = MemoryGuard()
        try:
            p = prepare(m, demo_event(m, 0))
            self.assertIsNone(p.report['unchanged_rate'])
            self.assertEqual(p.report['risk'], 'uncovered')
        finally:
            m.close()

    def test_duplicate_flood_keeps_essential_context_and_all_evidence(self):
        for i in range(30):
            self.m.ingest(dict(demo_event(self.m, 0), event_id=f'dup-{i}'))
        r = run_agent(self.m, dict(project='Atlas', version_scope='v1'))
        self.assertEqual(r['status'], 'call')
        self.assertLessEqual(r['context']['context_units'], 2048)
        path_fact = next(f for f in self.m.state()['facts'] if f['project']=='Atlas' and f['version_scope']=='v1' and f['attribute']=='login_path')
        self.assertEqual(len(path_fact['evidence']), 32)

    def test_fork_is_exact_prefix_and_independent(self):
        load_demo(self.m)
        branch = fork(self.m, 4)
        try:
            self.assertEqual(branch.state(), self.m.state(4))
            branch.ingest(dict(demo_event(branch, 0), event_id='branch'))
            self.assertEqual(self.m.state()['step'], 6)
            self.assertEqual(branch.state()['step'], 5)
        finally:
            branch.close()

    def test_history_does_not_use_future_facts(self):
        load_demo(self.m)
        r = history(self.m, 5)
        self.assertEqual(r['transitions'][0]['tested'], 0)
        self.assertEqual(r['blocked'], 1)
        self.assertEqual(r['recovered'], 0)
        self.assertEqual(history(self.m)['recovered'], 1)

    def test_failed_import_rolls_back_database(self):
        export = self.m.export()
        export['state']['facts'][0]['value'] = '/corrupt'
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as d:
            path = str(Path(d)/'bad.db')
            with self.assertRaises(ValueError):
                MemoryGuard.replay(export, path)
            m = MemoryGuard(path)
            try:
                self.assertEqual(m.state()['step'], 0)
            finally:
                m.close()

    def test_sessions_survive_restart_including_empty_session(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as d:
            path = str(Path(d)/'memory.db')
            w = Workspace(path)
            initial_hash = w.guard.state()['state_hash']
            w.create('空白')
            active = w.data['active']
            w.close()
            w = Workspace(path)
            try:
                self.assertEqual(w.data['active'], active)
                self.assertEqual(w.guard.state()['step'], 0)
                w.switch('initial')
                self.assertEqual(w.guard.state()['state_hash'], initial_hash)
                w.create('恢复', checkpoint=4)
                self.assertEqual(w.guard.state()['step'], 4)
            finally:
                w.close()

    def test_invalid_import_preserves_active_session(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as d:
            w = Workspace(str(Path(d)/'memory.db'))
            try:
                before = w.guard.state()
                bad = copy.deepcopy(w.guard.export())
                bad['state']['state_hash'] = 'wrong'
                with self.assertRaises(ValueError):
                    w.create(exported=bad)
                self.assertEqual(before, w.guard.state())
                self.assertEqual(len(w.list()['sessions']), 1)
            finally:
                w.close()
