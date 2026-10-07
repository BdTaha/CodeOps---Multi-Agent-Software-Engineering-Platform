"""Product planning jobs share the existing independent worker process."""
import logging
import threading

from autonomous_engineering.agents.planner import PlanningError
from autonomous_engineering.agents.product_planner import ProductPlanningAgent
from autonomous_engineering.infrastructure.ollama_product import OllamaProductPlanProvider
from autonomous_engineering.infrastructure.task_store import LostLease

logger = logging.getLogger(__name__)


def run_product_plan(config, store, owner, provider=None, worker_seen=None):
    store.settle_interrupted()
    job = store.claim(owner, config.lease_seconds)
    if job is None:
        return False
    finished = threading.Event()
    def heartbeat():
        while not finished.wait(config.lease_seconds / 3):
            try:
                if not store.heartbeat(job['id'], owner, config.lease_seconds):
                    return
                if worker_seen:
                    worker_seen()
            except Exception:
                logger.exception('Product planning heartbeat failed goal_id=%s', job['id'])
                return
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    agent = None
    try:
        if provider is None and config.ollama_model is None:
            raise PlanningError('MODEL_NOT_CONFIGURED', 'Configure ASE_OLLAMA_MODEL and start local Ollama to generate a project plan.')
        agent = ProductPlanningAgent(provider or OllamaProductPlanProvider(config))
        draft = agent.plan(job['goal'], store.project(job['project_id']))
        store.complete(job['id'], owner, draft, agent.attempts, getattr(agent.provider, 'model', None))
    except LostLease:
        logger.warning('Product plan stopped after lease loss goal_id=%s', job['id'])
    except Exception as exc:
        message = f'{exc.code}: {exc}' if isinstance(exc, PlanningError) else 'PLANNING_FAILED: Product planning failed; inspect the worker log and submit again.'
        if not isinstance(exc, PlanningError):
            logger.exception('Product planning failed goal_id=%s', job['id'])
        try:
            store.fail(job['id'], owner, message, agent.attempts if agent else 0, getattr(agent.provider, 'model', None) if agent else None)
        except LostLease:
            logger.warning('Discarded failed plan after lease loss goal_id=%s', job['id'])
    finally:
        finished.set()
        thread.join(timeout=1)
    return True
