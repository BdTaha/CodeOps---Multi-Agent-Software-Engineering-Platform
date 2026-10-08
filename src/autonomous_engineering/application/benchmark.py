"""Opt-in real-model benchmarks; only declared fixture paths may be approved."""
import argparse
import json
from pathlib import Path

from autonomous_engineering.application.worker import Worker
from autonomous_engineering.application.evaluation import metrics
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.workflows.state import WorkflowState


def run(dataset, config):
    store = TaskStore(config.database_url.get_secret_value())
    worker = Worker(config, store)
    results = []
    try:
        # Use an independent database for benchmarks: no unrelated queued jobs.
        if any(j['phase'].startswith('queued') for j in store.list(500)):
            raise ValueError('Use a separate benchmark database without queued jobs.')
        for case in json.loads(dataset.read_text(encoding='utf-8')):
            source = (dataset.parent / case['repository']).resolve()
            if not source.is_relative_to(config.repository_root.resolve()):
                raise ValueError('Benchmark fixture must stay within the repository root.')
            state = WorkflowState(task=TaskRecord(request=TaskRequest(repository_path=str(source),user_request=case['request'])))
            options = dict(run_tests=True,test_backend='docker',framework=case.get('framework','unittest'),max_attempts=3)
            task_id = store.create(state,options)['id']
            worker.run_once()
            job = store.get(task_id)
            if job['phase'] == 'awaiting_approval':
                paths = {p for step in job['snapshot']['plan']['steps'] for p in step['files']}
                if paths and paths <= set(case['allowed_paths']):
                    store.approve(task_id,job['approval'],options)
                    worker.run_once()
                else:
                    store.cancel(task_id); store.settle_interrupted()
            results.append(store.get(task_id))
        from autonomous_engineering.infrastructure.model_gateway import resolve_route
        route = resolve_route(config)
        return {'model':route.model,'provider':route.provider,'cases':results,'metrics':metrics(results)}
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dataset',type=Path)
    parser.add_argument('--approve-fixture-plans',action='store_true',required=True,
        help='Explicitly authorize changes only within dataset allowed_paths and offline container tests.')
    parser.add_argument('--output',type=Path,default=Path('benchmark-results.json'))
    args = parser.parse_args()
    result = run(args.dataset,Settings())
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result['metrics'],indent=2))


if __name__ == '__main__':
    main()
