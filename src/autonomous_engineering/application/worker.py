"""Independent leased worker; browser disconnects do not end jobs."""
import asyncio
import logging
import threading
import time
from uuid import uuid4

from autonomous_engineering.agents.developer import approval_identity
from autonomous_engineering.domain.execution import ExecutionError
from autonomous_engineering.domain.results import ReportSummary
from autonomous_engineering.domain.tasks import TaskStatus
from autonomous_engineering.infrastructure.ollama_developer import OllamaDevelopmentProvider
from autonomous_engineering.infrastructure.ollama_reviewer import OllamaReviewProvider
from autonomous_engineering.infrastructure.test_process import LocalTestProcess
from autonomous_engineering.infrastructure.docker_tests import DockerTestProcess
from autonomous_engineering.infrastructure.task_store import TaskStore, LostLease
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.application.product_planning import run_product_plan
from autonomous_engineering.workflows.development import develop_approved
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate
from autonomous_engineering.workflows.streaming import stream_workflow

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings, store=None, development_provider=None, review_provider=None, product_plan_provider=None, coding_plan_provider=None, evidence_provider=None):
        self.config = settings
        self.store = store or TaskStore(settings.database_url.get_secret_value())
        self.owner = str(uuid4())
        self.development_provider = development_provider
        self.review_provider = review_provider
        self.product_plan_provider = product_plan_provider
        self.coding_plan_provider = coding_plan_provider
        self.planning_store = PlanningStore(self.store.engine)
        from autonomous_engineering.infrastructure.acceptance_store import AcceptanceEvidenceStore
        self.evidence_store = AcceptanceEvidenceStore(settings,self.store,evidence_provider)

    def run_once(self):
        self.store.worker_seen(self.owner)
        self.store.settle_interrupted()
        if self.evidence_store.run_once(self.owner):
            return True
        job = self.store.claim(self.owner, self.config.lease_seconds)
        if job is None:
            return run_product_plan(self.config, self.planning_store, self.owner, self.product_plan_provider,
                worker_seen=lambda: self.store.worker_seen(self.owner))
        task_id = job['id']
        cancelled, finished = threading.Event(), threading.Event()
        def heartbeat():
            while not finished.wait(self.config.lease_seconds / 3):
                try:
                    self.store.worker_seen(self.owner)
                    if not self.store.heartbeat(task_id, self.owner, self.config.lease_seconds):
                        cancelled.set()
                        return
                except Exception:
                    cancelled.set()
                    logger.exception('Worker heartbeat failed task_id=%s', task_id)
                    return
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        def guard():
            if cancelled.is_set() or not self.store.heartbeat(task_id, self.owner, self.config.lease_seconds):
                raise LostLease('Task cancelled or lease lost before mutation.')
        def started(node):
            guard()
            self.store.checkpoint(task_id, self.owner, node=node, kind='node_started')
        def completed(node, state):
            self.store.checkpoint(task_id, self.owner, state, node=node)
        try:
            state = WorkflowState.model_validate(job['snapshot'])
            if job['phase'] == 'planning':
                asyncio.run(self.plan(task_id, state))
            else:
                options = job['options']
                if self.config.ollama_model is None and self.development_provider is None:
                    raise ValueError('Configure a local model before development.')
                values = state.model_dump()
                values['max_development_attempts'] = options['max_attempts']
                state = WorkflowState.model_validate(values)
                # Changing the attempt budget does not alter the approval identity.
                process = None
                if options['run_tests']:
                    process = DockerTestProcess(self.config, options['framework'], cancelled) if options['test_backend'] == 'docker' else LocalTestProcess(
                        self.config.test_timeout_seconds, framework=options['framework'], cancel_event=cancelled)
                result = develop_approved(state, self.config.workspace_root, job['approval'],
                    self.development_provider or OllamaDevelopmentProvider(self.config), test_process=process,
                    review_provider=self.review_provider or OllamaReviewProvider(self.config),
                    allow_repairs=options['max_attempts'] > 1, on_node_started=started,
                    on_node_completed=completed, before_write=guard)
                self.store.checkpoint(task_id, self.owner, result, phase=result.task.status.value, kind='task_finished')
        except LostLease:
            logger.warning('Worker stopped after cancellation/lease loss task_id=%s', task_id)
        except Exception:
            logger.exception('Worker task failed task_id=%s', task_id)
            latest = self.store.get(task_id)
            state = WorkflowState.model_validate(latest['snapshot'])
            if not state.task.status.terminal:
                if state.task.status == TaskStatus.PENDING:
                    state = state.apply(WorkflowUpdate(status=TaskStatus.RUNNING))
                message = 'Worker execution failed; inspect the server logs. No success is inferred.'
                state = state.apply(WorkflowUpdate(status=TaskStatus.FAILED, current_agent=None,
                    errors=(ExecutionError(code='WORKER_ERROR', message=message),), report=ReportSummary(outcome=TaskStatus.FAILED, summary=message)))
                try:
                    self.store.checkpoint(task_id, self.owner, state, phase='failed', kind='task_failed')
                except LostLease:
                    pass
        finally:
            finished.set()
            thread.join(timeout=2)
            self.store.settle_interrupted()
        return True

    async def plan(self, task_id, initial):
        final = initial
        async for event in stream_workflow(initial, settings=self.config, planner_provider=self.coding_plan_provider):
            if event.kind == 'node_started':
                self.store.checkpoint(task_id, self.owner, node=event.node, kind='node_started')
            if event.snapshot is not None:
                final = event.snapshot
                self.store.checkpoint(task_id, self.owner, final, node=event.node, kind=event.kind)
            if event.kind == 'node_completed' and event.node == 'plan_implementation' and final.plan is not None:
                token = approval_identity(final, self.config.workspace_root)
                self.store.checkpoint(task_id, self.owner, final, phase='awaiting_approval', approval=token, kind='approval_required')
                return
            if event.kind == 'run_error':
                raise RuntimeError('Planning stream failed.')
        self.store.checkpoint(task_id, self.owner, final, phase=final.task.status.value, kind='task_finished')

    def run(self, stop=None):
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                if not self.run_once():
                    stop.wait(self.config.worker_poll_seconds)
            except Exception:
                logger.exception('Worker polling failed')
                stop.wait(self.config.worker_poll_seconds)


def main():
    from autonomous_engineering.core.config import Settings
    from autonomous_engineering.core.logging import configure_logging
    config = Settings()
    configure_logging(config.log_level)
    Worker(config).run()


if __name__ == '__main__':
    main()
