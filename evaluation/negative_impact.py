"""Count/rate diagnostics over independently scored tool outcomes."""
from memory_guard.schema import digest


def summarize(rows):
    previous = {}
    regressions = eligible = contaminated = calls = 0
    for row in rows:
        prediction = row['prediction']
        if prediction['status'] == 'call':
            calls += 1
            cited = set(prediction['evidence_ids'])
            contaminated += any(f['fact_id'] in cited and (f['project'] != row['task'].get('project') or f['version_scope'] != row['task'].get('version_scope')) for f in row['context']['facts'])
        if row['category'] == 'anchor':
            task = {k:v for k,v in row['task'].items() if k != 'task_id'}
            key = (row['stream_id'], digest(task))
            if previous.get(key) is True:
                eligible += 1
                regressions += not row['success']
            previous[key] = bool(row['success'])
    def metric(n, d):
        return {'count':n, 'eligible':d, 'rate':n/d if d else None}
    return {
        'anchor_success_to_failure':metric(regressions, eligible),
        'stale_misuse':metric(sum(r['stale_misuse'] for r in rows), sum(r['stale_eligible'] for r in rows)),
        'wrong_strong_answer':metric(sum(r['wrong_strong_answer'] for r in rows), sum(not r['answerable'] for r in rows)),
        'excess_clarify':metric(sum(r['excess_clarify'] for r in rows), sum(r['answerable'] for r in rows)),
        'cross_scope_cited_calls':metric(contaminated, calls),
        'note':'基于同一合成集与独立模拟器评分；分母为0时rate=null。旧任务相邻成功→失败不等于通用模型灾难性遗忘。'
    }
