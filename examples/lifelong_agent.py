"""A dependency-free learn -> rehearse -> commit -> act integration example."""
import json
from memory_guard import MemoryGuard
from memory_guard.agent import run_agent
from memory_guard.impact import prepare, commit


def main():
    memory = MemoryGuard()
    try:
        memory.ingest(dict(event_id='seed', source_id='docs', project='Orion', version_scope='v1', text='登录路径为 /login；认证字段为 api_key。'))
        incoming = dict(event_id='unverified', source_id='notes', project='Orion', version_scope='v1', text='登录路径为 /new-login。')
        proposal = prepare(memory, incoming)
        print(json.dumps(proposal.report, ensure_ascii=False, indent=2))
        if proposal.report['requires_acknowledgement']:
            print('学习门控：发现影响，保留原记忆，交给使用者复核。')
        else:
            commit(memory, proposal)
        result = run_agent(memory, dict(project='Orion', version_scope='v1'))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        assert result['tool_args']['path'] == '/login'
    finally:
        memory.close()


if __name__ == '__main__':
    main()
