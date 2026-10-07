"""Transactional task snapshots, trace events, and fenced job leases."""
import json
import time
from uuid import uuid4

from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, Integer, Float, select, update, insert
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

from autonomous_engineering.workflows.state import WorkflowState

metadata = MetaData()
tasks = Table("tasks", metadata,
    Column("id", String(36), primary_key=True), Column("phase", String(32), nullable=False),
    Column("snapshot", Text, nullable=False), Column("options", Text, nullable=False),
    Column("approval", String(64)), Column("node", String(80)), Column("owner", String(36)),
    Column("lease", Float), Column("cancel", Integer, nullable=False, default=0),
    Column("revision", Integer, nullable=False, default=0), Column("created", Float, nullable=False),
    Column("delivery", Text, nullable=False, default="{}"))
events = Table("events", metadata, Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", String(36), nullable=False, index=True), Column("kind", String(40), nullable=False),
    Column("node", String(80)), Column("data", Text, nullable=False), Column("created", Float, nullable=False))
projects = Table("projects", metadata, Column("id", String(36), primary_key=True),
    Column("path", Text, nullable=False, unique=True), Column("data", Text, nullable=False))
workers = Table('workers', metadata, Column('id', String(36), primary_key=True), Column('seen', Float, nullable=False))


class LostLease(RuntimeError):
    pass


class TaskStore:
    def __init__(self, url: str):
        args = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            args["poolclass"] = StaticPool
        self.engine = create_engine(url, pool_pre_ping=True, **args)
        metadata.create_all(self.engine)

    def close(self):
        self.engine.dispose()

    @staticmethod
    def unpack(row):
        if row is None:
            return None
        item = dict(row)
        item["snapshot"] = json.loads(item["snapshot"])
        item["options"] = json.loads(item["options"])
        item["delivery"] = json.loads(item["delivery"])
        return item

    def create(self, state: WorkflowState, options: dict):
        task_id = str(state.task.task_id)
        with self.engine.begin() as db:
            db.execute(insert(tasks).values(id=task_id, phase="queued_planning", snapshot=state.model_dump_json(),
                options=json.dumps(options), created=time.time(), cancel=0, revision=0, delivery="{}"))
            self.event(db, task_id, "task_created", None, {"run_id": str(state.run_id)})
        return self.get(task_id)

    @staticmethod
    def event(db, task_id, kind, node, data):
        db.execute(insert(events).values(task_id=task_id, kind=kind, node=node, data=json.dumps(data), created=time.time()))

    def get(self, task_id):
        with self.engine.connect() as db:
            return self.unpack(db.execute(select(tasks).where(tasks.c.id == str(task_id))).mappings().first())

    def list(self, limit=100):
        with self.engine.connect() as db:
            return [self.unpack(row) for row in db.execute(select(tasks).order_by(tasks.c.created.desc()).limit(limit)).mappings()]

    def trace(self, task_id, after=0):
        with self.engine.connect() as db:
            return [{**dict(row), "data": json.loads(row["data"])} for row in db.execute(select(events).where(
                events.c.task_id == str(task_id), events.c.id > after).order_by(events.c.id).limit(500)).mappings()]

    def claim(self, owner, lease_seconds):
        with self.engine.begin() as db:
            row = db.execute(select(tasks).where(tasks.c.phase.in_(["queued_planning", "queued_development"]),
                tasks.c.cancel == 0).order_by(tasks.c.created).limit(1)).mappings().first()
            if row is None:
                return None
            phase = "planning" if row["phase"] == "queued_planning" else "development"
            result = db.execute(update(tasks).where(tasks.c.id == row["id"], tasks.c.phase == row["phase"],
                tasks.c.revision == row["revision"], tasks.c.cancel == 0).values(phase=phase, owner=owner,
                    lease=time.time() + lease_seconds, revision=row["revision"] + 1))
            if result.rowcount != 1:
                return None
            self.event(db, row["id"], "job_claimed", None, {"phase": phase})
        return self.get(row["id"])

    def heartbeat(self, task_id, owner, seconds):
        with self.engine.begin() as db:
            result = db.execute(update(tasks).where(tasks.c.id == str(task_id), tasks.c.owner == owner,
                tasks.c.lease > time.time(), tasks.c.cancel == 0).values(lease=time.time() + seconds))
            return result.rowcount == 1

    def checkpoint(self, task_id, owner, state=None, *, node=None, phase=None, approval=None, kind="node_completed"):
        values = {"node": node}
        if state is not None:
            values["snapshot"] = state.model_dump_json()
        if phase is not None:
            values.update(phase=phase, owner=None, lease=None, approval=approval, node=None)
        with self.engine.begin() as db:
            result = db.execute(update(tasks).where(tasks.c.id == str(task_id), tasks.c.owner == owner,
                tasks.c.lease > time.time(), tasks.c.cancel == 0).values(**values))
            if result.rowcount != 1:
                raise LostLease("Task lease ended or cancellation was requested.")
            self.event(db, str(task_id), kind, node, {"phase": phase, "execution_count": len(state.executions) if state else None})

    def approve(self, task_id, receipt, options):
        with self.engine.begin() as db:
            result = db.execute(update(tasks).where(tasks.c.id == str(task_id), tasks.c.phase == "awaiting_approval",
                tasks.c.approval == receipt, tasks.c.cancel == 0).values(phase="queued_development", options=json.dumps(options)))
            if result.rowcount != 1:
                return False
            self.event(db, str(task_id), "plan_approved", None, {"max_attempts": options["max_attempts"], "test_backend": options["test_backend"]})
        return True

    def cancel(self, task_id):
        with self.engine.begin() as db:
            result = db.execute(update(tasks).where(tasks.c.id == str(task_id), tasks.c.phase.in_(
                ["queued_planning", "planning", "awaiting_approval", "queued_development", "development"])).values(cancel=1))
            if result.rowcount:
                self.event(db, str(task_id), "cancel_requested", None, {})
        return bool(result.rowcount)

    def settle_interrupted(self):
        # Never repeat possibly completed writes after a crash. Preserve checkpoint,
        # fail visibly, and allow retry as a new run with a new isolated workspace.
        from autonomous_engineering.domain.tasks import TaskStatus
        from autonomous_engineering.domain.execution import ExecutionError
        from autonomous_engineering.domain.results import ReportSummary
        from autonomous_engineering.workflows.state import WorkflowUpdate
        with self.engine.begin() as db:
            rows = db.execute(select(tasks).where(tasks.c.cancel == 1, tasks.c.phase.not_in(["cancelled", "succeeded", "failed"]))).mappings().all()
            rows += db.execute(select(tasks).where(tasks.c.phase.in_(["planning", "development"]), tasks.c.lease < time.time(), tasks.c.cancel == 0)).mappings().all()
            for row in rows:
                cancelled = bool(row["cancel"])
                state = WorkflowState.model_validate_json(row["snapshot"])
                status = TaskStatus.CANCELLED if cancelled else TaskStatus.FAILED
                message = "Cancellation requested; no further workflow node will run." if cancelled else "Worker lease expired; inspect the retained checkpoint and retry as a new run."
                if not state.task.status.terminal:
                    if not cancelled and state.task.status == TaskStatus.PENDING:
                        state = state.apply(WorkflowUpdate(status=TaskStatus.RUNNING))
                    state = state.apply(WorkflowUpdate(status=status, current_agent=None,
                        errors=(ExecutionError(code="TASK_CANCELLED" if cancelled else "WORKER_INTERRUPTED", message=message),),
                        report=ReportSummary(outcome=status, summary=message)))
                status = state.task.status
                result = db.execute(update(tasks).where(tasks.c.id == row["id"], tasks.c.revision == row["revision"],
                    tasks.c.owner == row["owner"], tasks.c.lease == row["lease"], tasks.c.cancel == row["cancel"]).values(
                    phase=status.value, snapshot=state.model_dump_json(), owner=None, lease=None, node=None, revision=row["revision"] + 1))
                if result.rowcount == 1:
                    self.event(db, row["id"], status.value, row["node"], {})

    def register(self, path, data):
        try:
            return self._register(path, data)
        except IntegrityError:
            with self.engine.connect() as db:
                return json.loads(db.execute(select(projects.c.data).where(projects.c.path == path)).scalar_one())

    def _register(self, path, data):
        with self.engine.begin() as db:
            row = db.execute(select(projects).where(projects.c.path == path)).mappings().first()
            if row:
                return json.loads(row["data"])
            item = {"id": str(uuid4()), "path": path, **data}
            db.execute(insert(projects).values(id=item["id"], path=path, data=json.dumps(item)))
            return item

    def projects(self):
        with self.engine.connect() as db:
            return [json.loads(row) for row in db.execute(select(projects.c.data)).scalars()]

    def worker_seen(self, owner):
        with self.engine.begin() as db:
            if not db.execute(update(workers).where(workers.c.id == owner).values(seen=time.time())).rowcount:
                db.execute(insert(workers).values(id=owner, seen=time.time()))

    def active_workers(self, seconds):
        with self.engine.connect() as db:
            return len(db.execute(select(workers.c.id).where(workers.c.seen > time.time()-seconds)).all())

    def delivery(self, task_id, value):
        with self.engine.begin() as db:
            db.execute(update(tasks).where(tasks.c.id == str(task_id)).values(delivery=json.dumps(value)))

    def lock_delivery(self, task_id, previous):
        with self.engine.begin() as db:
            result = db.execute(update(tasks).where(tasks.c.id == str(task_id), tasks.c.delivery == json.dumps(previous)).values(
                delivery=json.dumps({**previous, "publishing": True})))
            return result.rowcount == 1
