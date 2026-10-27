"""Run from the repository root: python -m examples.api_agent.agent"""
import json
from memory_guard import MemoryGuard
from memory_guard.agent import run_agent
from memory_guard.demo import load_demo
from .mock_tool import mock_api_call

if __name__ == "__main__":
    memory = MemoryGuard()
    load_demo(memory)
    result = run_agent(memory, {"project": "Atlas", "version_scope": "v2"})
    result["execution_result"] = mock_api_call([{"project": "Atlas", "version": "v2", "path": "/auth/token", "auth_field": "access_token"}], result["tool_args"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
