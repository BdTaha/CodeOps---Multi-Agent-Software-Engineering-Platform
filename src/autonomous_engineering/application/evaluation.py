"""Metrics derived only from persisted execution evidence."""
import argparse
import json
from pathlib import Path


def metrics(items):
    settled = [item for item in items if item['phase'] in {'succeeded','failed','cancelled'}]
    success = sum(item['phase']=='succeeded' for item in settled)
    measured = [item['snapshot'] for item in settled if item['snapshot']['executions']]
    tested = [s['tests'] for s in measured if s.get('tests') and s['tests']['outcome'] != 'skipped']
    counts = [test['counts'] for test in tested if test.get('counts')]
    executions = [record for state in measured for record in state['executions']]
    input_tokens = [e['input_tokens'] for e in executions if e.get('input_tokens') is not None]
    output_tokens = [e['output_tokens'] for e in executions if e.get('output_tokens') is not None]
    case_total = sum(c['passed']+c['failed'] for c in counts)
    return {'scope':'Most recent 500 tasks at most; actual recorded results only', 'observed_tasks':len(items),
        'terminal_tasks':len(settled),'successful_tasks':success,
        'task_success_rate':success/len(settled) if settled else None,
        'test_run_pass_rate':sum(t['outcome']=='passed' for t in tested)/len(tested) if tested else None,
        'test_case_pass_rate':sum(c['passed'] for c in counts)/case_total if case_total else None,
        'test_runs_with_unknown_counts':sum(t.get('counts') is None for t in tested),
        'average_agent_seconds':sum(sum(e['duration_seconds'] for e in s['executions']) for s in measured)/len(measured) if measured else None,
        'average_development_attempts':sum(s['development_attempts'] for s in measured)/len(measured) if measured else None,
        'failed_agent_actions':sum(e['status']=='failed' for e in executions),
        'input_tokens_observed':sum(input_tokens) if input_tokens else None,
        'output_tokens_observed':sum(output_tokens) if output_tokens else None,
        'executions_without_token_evidence':sum(e.get('input_tokens') is None for e in executions),
        'llm_cost':None,'cost_note':'No monetary cost telemetry is available for the local provider.'}


def main():
    from autonomous_engineering.core.config import Settings
    from autonomous_engineering.infrastructure.task_store import TaskStore
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('evaluation.json'))
    args = parser.parse_args()
    store = TaskStore(Settings().database_url.get_secret_value())
    result = metrics(store.list(500))
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    store.close()


if __name__ == '__main__':
    main()
