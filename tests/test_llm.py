import io
import json
import unittest
from unittest.mock import patch

from memory_guard import MemoryGuard
from memory_guard.agent import run_agent
from memory_guard.llm import ChatPlanner


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.task = dict(project="Atlas", version_scope="v1", query="请用记忆里的接口登录")
        self.context = dict(checkpoint_id="cp", status="ok", facts=[
            dict(fact_id="path-1", attribute="login_path", value="/sign-in"),
            dict(fact_id="auth-1", attribute="auth_field", value="ticket"),
        ])
        self.prediction = dict(status="call", tool_args=dict(project="Atlas", version="v1",
            operation="login", path="/sign-in", auth_field="ticket", payload={"username": "demo"}),
            evidence_ids=["path-1", "auth-1"], reason="Use documented evidence")

    def response(self, prediction=None, finish="stop"):
        return io.BytesIO(json.dumps(dict(choices=[dict(finish_reason=finish, message=dict(
            content=json.dumps(prediction or self.prediction)))], usage=dict(prompt_tokens=30,
            completion_tokens=20, total_tokens=50))).encode())

    def test_real_adapter_sends_shared_prompt_and_keeps_raw_output(self):
        with patch("urllib.request.urlopen", return_value=self.response()) as request:
            result = ChatPlanner()(self.task, self.context)
        self.assertEqual(result["tool_args"], self.prediction["tool_args"])
        self.assertEqual(result["generation_model_calls"], 1)
        self.assertEqual(result["token_usage"]["total_tokens"], 50)
        sent = json.loads(request.call_args.args[0].data)
        self.assertFalse(sent["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(sent, result["model_trace"]["request"])
        self.assertIn("raw_response", result["model_trace"])

    def test_empty_memory_still_reaches_model(self):
        clarification = dict(status="clarify", tool_args=None, evidence_ids=[], reason="Missing evidence")
        with patch("urllib.request.urlopen", return_value=self.response(clarification)) as request:
            result = ChatPlanner()(self.task, dict(status="ok", facts=[]))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["status"], "clarify")
        schema = json.loads(request.call_args.args[0].data)["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["status"]["enum"], ["clarify"])

    def test_model_cannot_bypass_known_memory_conflict(self):
        context = dict(self.context, status="clarify", conflicts=[{"attribute": "login_path"}])
        with patch("urllib.request.urlopen", return_value=self.response()):
            result = ChatPlanner()(self.task, context)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["tool_args"])

    def test_network_failure_is_error_without_rule_fallback_or_retry(self):
        with patch("urllib.request.urlopen", side_effect=OSError("unavailable")) as request:
            result = ChatPlanner()(self.task, self.context)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["tool_args"])
        self.assertIn("unavailable", result["model_trace"]["error"])

    def test_truncated_output_and_invented_citations_are_errors(self):
        with patch("urllib.request.urlopen", return_value=self.response(finish="length")):
            result = ChatPlanner()(self.task, self.context)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["token_usage"]["total_tokens"], 50)
        self.prediction["evidence_ids"] = ["invented"]
        with patch("urllib.request.urlopen", return_value=self.response()):
            self.assertEqual(ChatPlanner()(self.task, self.context)["status"], "error")

    def test_model_errors_are_scored_answers_not_repaired(self):
        self.prediction["tool_args"]["path"] = "/wrong"
        with patch("urllib.request.urlopen", return_value=self.response()):
            result = ChatPlanner()(self.task, self.context)
        self.assertEqual(result["status"], "call")
        self.assertEqual(result["tool_args"]["path"], "/wrong")

    def test_administrative_stage_ids_do_not_reach_the_model(self):
        task = dict(self.task, task_id="authorized_correction", answer="private")
        with patch("urllib.request.urlopen", return_value=self.response()):
            result = ChatPlanner()(task, self.context)
        public = json.loads(result["model_trace"]["request"]["messages"][1]["content"])["task"]
        self.assertEqual(public, self.task)

    def test_sdk_injection_preserves_readonly_memory(self):
        memory = MemoryGuard()
        try:
            memory.ingest(dict(event_id="seed", source_id="docs", project="Atlas", version_scope="v1",
                               text="登录路径为 /sign-in；认证字段为 ticket。"))
            before = memory.state()["state_hash"]
            def planner(task, context):
                return dict(status="clarify", tool_args=None, evidence_ids=[], reason="model choice")
            result = run_agent(memory, self.task, planner=planner)
            self.assertEqual(result["reason"], "model choice")
            self.assertEqual(before, memory.state()["state_hash"])
        finally:
            memory.close()


if __name__ == "__main__":
    unittest.main()
