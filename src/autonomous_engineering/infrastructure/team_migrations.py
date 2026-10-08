"""Transactional, idempotent migration of legacy project-scoped identities."""
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import MetaData, Table, inspect, insert, select
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.infrastructure.team_tables import TEAM_TABLES, members, skills, memberships, assignments, migrations, workspace_state, _insert

VERSION = 'workspace-identities-v1'


def initialize_team_schema(engine):
    with engine.begin() as db:
        if db.dialect.name == 'sqlite':
            db.exec_driver_sql('BEGIN IMMEDIATE')
        elif db.dialect.name == 'postgresql':
            db.exec_driver_sql('SELECT pg_advisory_xact_lock(50133677)')
        for table in TEAM_TABLES:
            table.create(db, checkfirst=True)
        # Additive bridge schema shares the startup migration fence, including
        # databases where the earlier workspace migration already completed.
        from autonomous_engineering.infrastructure.task_execution_tables import execution_links
        execution_links.create(db, checkfirst=True)
        from autonomous_engineering.infrastructure.acceptance_tables import initialize_acceptance_schema
        initialize_acceptance_schema(db)
        from autonomous_engineering.infrastructure.preview_tables import preview_profiles, execution_previews
        preview_profiles.create(db, checkfirst=True)
        execution_previews.create(db, checkfirst=True)
        from autonomous_engineering.infrastructure.planning_drafts import DRAFT_TABLES
        for table in DRAFT_TABLES:
            table.create(db, checkfirst=True)
        db.execute(_insert(db)(workspace_state).values(id='local', revision=0).on_conflict_do_nothing(index_elements=['id']))
        if db.execute(select(migrations.c.version).where(migrations.c.version == VERSION)).first():
            return
        inspector = inspect(db)
        if inspector.has_table('team_members'):
            old_metadata = MetaData()
            old_members = Table('team_members', old_metadata, autoload_with=db)
            old_skills = Table('team_member_skills', old_metadata, autoload_with=db)
            for row in db.execute(select(old_members)).mappings():
                values = dict(row)
                project_id, squad_id = values.pop('project_id'), values.pop('squad_id')
                values['max_concurrent_executions'] = values.pop('max_concurrent_tasks')
                db.execute(insert(members).values(**values))
                db.execute(insert(memberships).values(id=str(uuid5(NAMESPACE_URL, f"codeops-membership:{project_id}:{row['id']}")),
                    project_id=project_id, member_id=row['id'], squad_id=squad_id, active=True,
                    created_at=row['created_at'], revision=0))
            for row in db.execute(select(old_skills)).mappings():
                db.execute(insert(skills).values(**dict(row)))
            _retarget_assignments(db)
        db.execute(insert(migrations).values(version=VERSION, completed_at=utc_now().isoformat()))


def _retarget_assignments(db):
    old_fk = next((fk for fk in inspect(db).get_foreign_keys('engineering_task_assignments') if fk['referred_table'] == 'team_members'), None)
    if old_fk is None:
        return
    if db.dialect.name == 'postgresql':
        quote = db.dialect.identifier_preparer.quote
        db.exec_driver_sql(f'ALTER TABLE engineering_task_assignments DROP CONSTRAINT {quote(old_fk["name"])}')
        db.exec_driver_sql('ALTER TABLE engineering_task_assignments ADD CONSTRAINT fk_assignment_workspace_member FOREIGN KEY (assignee_id) REFERENCES workspace_members(id)')
    else:
        # SQLite cannot alter a FK. Copy all rows and replace only this table
        # within BEGIN IMMEDIATE. Legacy member/skill tables remain untouched.
        temporary_metadata = MetaData()
        for table in assignments.metadata.sorted_tables:
            table.to_metadata(temporary_metadata)
        temporary = assignments.to_metadata(temporary_metadata, name='engineering_task_assignments_workspace_migration')
        temporary.create(db)
        names = [column.name for column in assignments.columns]
        db.execute(insert(temporary).from_select(names, select(*assignments.columns)))
        db.exec_driver_sql('DROP TABLE engineering_task_assignments')
        db.exec_driver_sql('ALTER TABLE engineering_task_assignments_workspace_migration RENAME TO engineering_task_assignments')
