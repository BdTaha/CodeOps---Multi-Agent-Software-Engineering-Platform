"""Separate bounded startup/reconciliation service; no AI runtime slot usage."""
import logging
import threading
from uuid import uuid4
from autonomous_engineering.core.config import Settings
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.infrastructure.team_store import TeamStore
from autonomous_engineering.infrastructure.task_execution_store import TaskExecutionStore
from autonomous_engineering.infrastructure.preview_store import PreviewStore

def main():
    from autonomous_engineering.core.logging import configure_logging
    config=Settings();configure_logging(config.log_level)
    store=TaskStore(config.database_url.get_secret_value())
    bridge=TaskExecutionStore(config,store,TeamStore(PlanningStore(store.engine)))
    previews=PreviewStore(bridge);owner=str(uuid4());stop=threading.Event()
    def reconcile():
        while not stop.is_set():
            try: previews.reconcile()
            except Exception: logging.getLogger(__name__).exception('Preview cleanup/reconciliation failed; retrying.')
            stop.wait(config.preview_poll_seconds)
    # Cleanup/TTL remains responsive while another bounded startup is in progress.
    cleanup=threading.Thread(target=reconcile,name='preview-cleanup',daemon=True);cleanup.start()
    try:
        while not stop.is_set():
            try: previews.run_once(owner)
            except Exception: logging.getLogger(__name__).exception('Preview lifecycle reconciliation failed; resources remain tracked.')
            stop.wait(config.preview_poll_seconds)
    except KeyboardInterrupt: pass
    finally:
        stop.set();cleanup.join(timeout=20);store.close()

if __name__=='__main__': main()
