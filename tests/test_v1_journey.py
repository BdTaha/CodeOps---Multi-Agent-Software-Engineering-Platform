"""Actual SQL/API/worker/filesystem/test/export journey, explicit model fixtures.

No frontend mock, external inference, or Docker is needed for normal CI.
ASE_INTEGRATION_PREVIEWS adds a real Docker preview in the same journey.
"""
import hashlib
import os
from pathlib import Path
import shutil
import urllib.request
import pytest
from fastapi.testclient import TestClient
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.results import ImplementationPlan
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.infrastructure.docker_previews import DockerPreviewRuntime
from autonomous_engineering.application.worker import Worker
from autonomous_engineering.platform import create_platform_app
from test_product_planning import Provider
from test_developer import FixtureDeveloper
from test_reviewer import FixtureReview
from test_workspace_resources import resource, join

ROOT=Path(__file__).resolve().parents[1]
REGISTRATION='''import sqlite3
from contextlib import closing
from validation import normalize_email

def register(name, email, database='users.db'):
    email = normalize_email(email)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('Invalid name')
    with closing(sqlite3.connect(database)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY, name TEXT NOT NULL)')
        try:
            db.execute('INSERT INTO users (email, name) VALUES (?, ?)', (email, name.strip()))
        except sqlite3.IntegrityError:
            raise ValueError('Email already registered') from None
    return {'email': email, 'name': name.strip()}
'''
FIRST=REGISTRATION.replace('from validation import normalize_email','import re').replace('    email = normalize_email(email)',"    if not isinstance(email, str) or not re.fullmatch(r'[^\\s@]+@[^\\s@]+\\.[^\\s@]+', email.strip()):\n        raise ValueError('Invalid email')\n    email = email.strip().lower()")
TESTS='''import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from registration import register

class Registration(unittest.TestCase):
    def test_persists_and_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'users.db')
            self.assertEqual(register(' Ada ', ' ADA@Example.com ', path), {'name':'Ada','email':'ada@example.com'})
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT name FROM users').fetchone(), ('Ada',))
            with self.assertRaises(ValueError):
                register('Another', 'ada@example.com', path)
    def test_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'users.db')
            for name, email in [('Ada','bad'), ('','ada@example.com'), ('Ada',None)]:
                with self.subTest(name=name,email=email), self.assertRaises(ValueError):
                    register(name,email,path)
'''

class CodingPlan:
    def generate(self, context):
        return ImplementationPlan(problem_interpretation='Explicit test: implement registration and tests',steps=[dict(description='Add registration with SQLite and helper reuse',files=['registration.py','tests/test_registration.py'])],context_files=['validation.py','app.py'],tests_to_run=['Run unittest discover'])

def digest(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}

def test_registration_v1_full_journey(tmp_path,monkeypatch):
    git_dir=Path(r'C:\Program Files\Git\cmd')
    if git_dir.is_dir():monkeypatch.setenv('PATH',str(git_dir)+os.pathsep+os.environ['PATH'])
    if not shutil.which('git'):pytest.skip('Git required for explicit export')
    source=tmp_path/'developer-demo';shutil.copytree(ROOT/'examples'/'developer-demo',source)
    before=digest(source)
    settings=Settings(_env_file=None,environment='test',repository_root=tmp_path,workspace_root=tmp_path/'snapshots',test_backend='local')
    store=TaskStore('sqlite:///'+str(tmp_path/'journey.db'));planning=PlanningStore(store.engine)
    try:
        app=create_platform_app(settings,store)
        with TestClient(app) as client:
            registered=client.post('/projects',json=dict(path=str(source),name='developer-demo'));assert registered.status_code==201,registered.text
            project=registered.json();project_id=project['id']
            queued=client.post(f'/projects/{project_id}/plans',json=dict(goal='Add user registration with input validation and persistent storage.')).json()
            draft=dict(title='Registration',summary='Use the existing API and email helper',assumptions=[],epics=[dict(ref='E1',title='Registration',description='Persist validated users')],tasks=[dict(ref='T1',epic_ref='E1',title='Implement registration with validation and persistent storage',description='Add registration.py for app.py; reuse validation.normalize_email and SQLite; include unittest tests.',priority='high',estimated_hours=8,technical_area='Backend',dependencies=[],acceptance_criteria=[dict(description='Valid input persists in SQLite'),dict(description='Duplicate and malformed email are rejected')])])
            provider=Provider([draft]);assert Worker(settings,store,product_plan_provider=provider).run_once()
            record=planning.get(queued['goal']['id']);assert record.status=='draft' and record.planning_basis.mode=='repository_grounded'
            assert 'validation.py' in record.planning_basis.inspected_files
            assert client.get(f'/projects/{project_id}/engineering-tasks').json()['tasks']==[]
            ai=resource(client,ai=True,name='Backend Agent');join(client,project,ai,'Backend Squad')
            capacity=client.get(f"/workspace/members/{ai['id']}/capacity").json();assert capacity['assigned_queue_depth']==0
            draft['tasks'][0]['estimated_hours']=5;draft['tasks'][0]['acceptance_criteria'].append(dict(description='Existing validation helper is reused'))
            saved=client.put(f"/product-plans/{record.goal.id}/draft",json=dict(revision=0,draft=draft));assert saved.status_code==200,saved.text
            assert client.post(f"/product-plans/{record.goal.id}/approve",json=dict(revision=0)).status_code==409
            approved=client.post(f"/product-plans/{record.goal.id}/approve",json=dict(revision=1));assert approved.status_code==200,approved.text
            assert approved.json()['materialization']=={'T1':'CO-1'}
            task=approved.json()['plan']['tasks'][0]
            assert client.get(f'/projects/{project_id}/engineering-tasks').json()['tasks'][0]['id']==task['id']
            assignment=client.post(f"/engineering-tasks/{task['id']}/assignment",json=dict(assignee_id=ai['id'],revision=task['revision']));assert assignment.status_code==200,assignment.text
            task=planning.task(task['id']).model_dump(mode='json')
            initial=client.post(f"/engineering-tasks/{task['id']}/executions",json=dict(revision=task['revision']));assert initial.status_code==202,initial.text
            job_id=initial.json()['execution']['id'];results=[]
            for attempt,implementation in enumerate([FIRST,REGISTRATION]):
                # Request Changes starts a fresh source snapshot, preserving the old run.
                developer=FixtureDeveloper(edits=[dict(path='registration.py',kind='created',content=implementation,summary='Registration implementation'),dict(path='tests/test_registration.py',kind='created',content=TESTS,summary='Persistence and invalid input tests')])
                worker=Worker(settings,store,developer,FixtureReview(),coding_plan_provider=CodingPlan())
                assert worker.run_once();job=store.get(job_id);assert job['phase']=='awaiting_approval' and not developer.called
                assert digest(source)==before
                approval=client.post(f'/tasks/{job_id}/approve',json=dict(approval_id=job['approval'],run_tests=True,test_backend='local',framework='unittest',max_attempts=1));assert approval.status_code==202,approval.text
                assert worker.run_once();job=store.get(job_id);assert job['phase']=='succeeded',job['snapshot']['errors']
                assert job['snapshot']['tests']['outcome']=='passed' and job['snapshot']['review']['approved']
                assert worker.run_once()
                result=client.get(f"/engineering-tasks/{task['id']}/execution").json();results.append(result)
                assert result['task']['status']=='review' and result['acceptance_evidence']['version']
                assert digest(source)==before
                if attempt==0:
                    if os.environ.get('ASE_INTEGRATION_PREVIEWS'):
                        profile=client.put(f'/projects/{project_id}/preview-profile',json=dict(name='Registration demo',preview_type='web',runtime='python',enabled=True,start_command=['python','app.py'],health_path='/health',timeout_seconds=30));assert profile.status_code==200,profile.text
                        previews=app.state.preview_store;previews.runtime=DockerPreviewRuntime(settings)
                        preview=client.post(f"/engineering-tasks/{task['id']}/preview",json=dict(revision=result['task']['revision'],execution_task_id=job_id)).json()
                        try:
                            assert previews.run_once('v1-demo')
                            ready=previews.get(preview['id']);assert ready['status']=='ready',ready
                            with urllib.request.urlopen(ready['preview_url'],timeout=5) as page:assert b'Registration demo' in page.read()
                            request=urllib.request.Request(ready['preview_url'].rstrip('/')+'/register',data=b'{"name":"Ada","email":"ada@example.com"}',headers={'Content-Type':'application/json'})
                            with urllib.request.urlopen(request,timeout=5) as response:assert response.status==201
                        finally:previews.stop(preview['id']);previews.reconcile()
                    changes=client.post(f"/engineering-tasks/{task['id']}/request-changes",json=dict(revision=result['task']['revision'],execution_task_id=job_id,feedback="Use the project's existing validation helper instead of duplicating validation."));assert changes.status_code==202,changes.text
                    assert changes.json()['current']['parent_execution_task_id']==job_id
                    job_id=changes.json()['execution']['id']
            assert len(results[1]['history'])==2 and results[1]['history'][0]['review_state']=='changes_requested'
            assert Path(results[0]['execution']['snapshot']['workspace_path'],'registration.py').read_text()==FIRST
            latest=results[1]
            accepted=client.post(f"/engineering-tasks/{task['id']}/accept",json=dict(revision=latest['task']['revision'],execution_task_id=job_id,evidence_version=latest['acceptance_evidence']['version'],unresolved_acknowledged=True));assert accepted.status_code==200,accepted.text
            assert accepted.json()['task']['status']=='done' and store.get(job_id)['delivery']=={}
            receipt=client.get(f'/tasks/{job_id}/delivery').json()['receipt']
            exported=client.post(f'/tasks/{job_id}/delivery',json=dict(receipt=receipt,action='export'));assert exported.status_code==200,exported.text
            assert len(exported.json()['commit'])==40 and Path(exported.json()['archive']).is_file()
            assert digest(source)==before
    finally:store.close()
