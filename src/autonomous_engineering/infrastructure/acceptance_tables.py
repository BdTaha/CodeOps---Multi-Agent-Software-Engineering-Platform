"""Per-run frozen requirements, normalized evidence and local acceptance audit."""
from sqlalchemy import MetaData, Table, Column, String, Text, Integer, Boolean, Float, ForeignKey, ForeignKeyConstraint
from autonomous_engineering.infrastructure.task_store import tasks
from autonomous_engineering.infrastructure.planning_store import criteria

evidence_metadata = MetaData()
evidence_runs = Table('acceptance_evidence_runs', evidence_metadata,
    Column('execution_task_id', String(36), ForeignKey(tasks.c.id), primary_key=True),
    Column('version', String(36), nullable=False, unique=True),
    Column('mapper_version', String(100), nullable=False),
    Column('state', String(20), nullable=False),
    Column('created_at', String(40), nullable=False), Column('completed_at', String(40)),
    Column('owner', String(36)), Column('lease', Float), Column('error', Text))
run_criteria = Table('acceptance_run_criteria', evidence_metadata,
    Column('execution_task_id', String(36), ForeignKey(evidence_runs.c.execution_task_id), primary_key=True),
    Column('criterion_id', String(36), ForeignKey(criteria.c.id), primary_key=True),
    Column('position', Integer, nullable=False), Column('description', Text, nullable=False),
    Column('verification_status', String(20), nullable=False), Column('conflict', Boolean, nullable=False))
evidence_items = Table('acceptance_evidence_items', evidence_metadata,
    Column('id', String(36), primary_key=True),
    Column('execution_task_id', String(36), nullable=False, index=True),
    Column('criterion_id', String(36), nullable=False),
    Column('source_id', String(180), nullable=False), Column('evidence_type', String(24), nullable=False),
    Column('reference', Text, nullable=False), Column('summary', Text, nullable=False),
    Column('negative', Boolean, nullable=False), Column('executed', Boolean, nullable=False),
    Column('mapping', String(20), nullable=False), Column('created_at', String(40), nullable=False),
    ForeignKeyConstraint(['execution_task_id','criterion_id'],[run_criteria.c.execution_task_id,run_criteria.c.criterion_id]))
acceptance_audits = Table('acceptance_result_audits', evidence_metadata,
    Column('execution_task_id', String(36), ForeignKey(tasks.c.id), primary_key=True),
    Column('accepted_at', String(40), nullable=False), Column('action', String(40), nullable=False),
    Column('evidence_version', String(36)), Column('mapper_version', String(100)),
    Column('evidence_state', String(20), nullable=False), Column('evidence_digest', String(64), nullable=False),
    Column('unresolved_acknowledged', Boolean, nullable=False))

def initialize_acceptance_schema(db):
    from uuid import uuid5, NAMESPACE_URL
    from sqlalchemy import inspect, select, update
    if 'id' not in {col['name'] for col in inspect(db).get_columns(criteria.name)}:
        db.exec_driver_sql('ALTER TABLE engineering_acceptance_criteria ADD COLUMN id VARCHAR(36)')
    for row in db.execute(select(criteria).where(criteria.c.id.is_(None))).mappings():
        db.execute(update(criteria).where(criteria.c.task_id==row['task_id'],criteria.c.position==row['position'])
            .values(id=str(uuid5(NAMESPACE_URL,f"codeops-criterion:{row['task_id']}:{row['position']}"))))
    db.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_acceptance_criterion_id ON engineering_acceptance_criteria (id)')
    for table in evidence_metadata.sorted_tables:
        table.create(db, checkfirst=True)
