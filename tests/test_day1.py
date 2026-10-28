import json
import tempfile
import unittest
from pathlib import Path

from evaluation.build_day1 import make_stream
from evaluation.day1 import evaluate, summarize
from memory_guard.agent import plan


class DayOneTests(unittest.TestCase):
    def test_dataset_has_separate_names_and_four_stages(self):
        dev, _ = make_stream("dev", 0)
        acceptance, labels = make_stream("acceptance", 0)
        self.assertNotEqual(dev["stream_id"], acceptance["stream_id"])
        self.assertEqual(len(acceptance["checkpoints"]), 4)
        self.assertEqual(len(acceptance["probes"]), 12)
        self.assertEqual(set(labels["answers"]), {p["task"]["task_id"] for p in acceptance["probes"]})
        self.assertNotIn("answers", acceptance)

    def test_same_planner_budget_logs_and_real_regression_pairs(self):
        calls = []
        def planner(task, context):
            self.assertNotIn("answerable", task)
            self.assertNotIn("spec", context)
            from memory_guard.schema import canonical
            self.assertLessEqual(len(canonical(context["facts"]).encode("utf-8")), 2048)
            calls.append((task["task_id"], context["mode"]))
            return plan(task, context)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run"
            summary = evaluate(planner, out, "dev", limit_streams=1)
            self.assertEqual(len(calls), 36)
            self.assertEqual(summary["total_executions"], 36)
            self.assertEqual(summary["methods"]["latest"]["old_task_regression"]["count"], 1)
            self.assertGreater(summary["methods"]["latest"]["old_task_regression"]["total"], 0)
            self.assertEqual(summary["methods"]["governed"]["old_task_regression"]["count"], 0)
            self.assertIsNone(summary["methods"]["no_memory"]["old_task_regression"]["rate"])
            rows = [json.loads(s) for s in (out / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(r["state_hash_before"] == r["state_hash_after"] for r in rows))
            self.assertTrue(all(r["success"] for r in rows if r["method"] == "governed" and r["answerable"]))
            with self.assertRaises(FileExistsError):
                evaluate(planner, out, "dev", limit_streams=1)

    def test_model_failure_stays_error_and_is_logged(self):
        def failing(task, context):
            raise RuntimeError("model unavailable")
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "errors"
            summary = evaluate(failing, out, "dev", limit_streams=1)
            self.assertEqual(sum(m["planner_errors"] for m in summary["methods"].values()), 36)
            self.assertEqual(len((out / "raw.jsonl").read_text(encoding="utf-8").splitlines()), 36)

    def test_changed_or_unanswerable_old_answer_is_not_regression(self):
        base = dict(stream_id="s", task_key="s/old", category="anchor", stage="a", step=1,
                    answerable=True, answer_hash="old", task_hash="same-public-task", success=True,
                    prediction={"status": "call"})
        changed = dict(base, step=2, stage="b", answer_hash="new", success=False)
        conflict = dict(base, step=2, stage="b", answerable=False, success=False,
                        prediction={"status": "clarify"})
        self.assertEqual(summarize([base, changed])["old_task_regression"]["total"], 0)
        self.assertEqual(summarize([base, conflict])["old_task_regression"]["total"], 0)
        changed_prompt = dict(base, step=2, stage="b", task_hash="different-query", success=False)
        self.assertEqual(summarize([base, changed_prompt])["old_task_regression"]["total"], 0)
        failure = dict(base, step=2, stage="b", success=False, prediction={"status": "clarify"})
        self.assertEqual(summarize([base, failure])["old_task_regression"], {"count": 1, "total": 1, "rate": 1.0})


if __name__ == "__main__":
    unittest.main()
