"""Compact UI projections must not discard or mutate retained execution evidence."""
from autonomous_engineering.api.artifacts import compact_job
from fastapi.testclient import TestClient
from autonomous_engineering.core.config import Settings
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.platform import create_platform_app
from test_developer import planned


def test_compact_projection_leaves_full_artifacts_untouched():
    original={'id':'test','snapshot':{'development':{'diff':'VERY_LARGE_DIFF','original_files':{'app.py':'VERY_LARGE_BASELINE'}},
        'executions':[{'operation':'develop_implementation','status':'succeeded'}],
        'tests':{'outcome':'passed','counts':{'passed':3,'failed':0,'skipped':0},'executions':[{'command':['pytest'],'exit_code':0,'output_summary':'VERY_LARGE_LOG'}]}}}
    compact=compact_job(original)
    assert compact['snapshot']['development']['diff']==''
    assert compact['snapshot']['development']['original_files']=={}
    assert compact['snapshot']['tests']['executions'][0]['output_summary']==''
    assert compact['snapshot']['tests']['counts']==original['snapshot']['tests']['counts']
    assert original['snapshot']['development']['diff']=='VERY_LARGE_DIFF'
    assert original['snapshot']['tests']['executions'][0]['output_summary']=='VERY_LARGE_LOG'


def test_compact_job_endpoint_preserves_default_contract(planned,tmp_path):
    state,_,_=planned
    config=Settings(_env_file=None,database_url='sqlite:///'+str(tmp_path/'ui.db'),workspace_root=tmp_path/'work')
    store=TaskStore(config.database_url.get_secret_value())
    try:
        created=store.create(state,{'test_backend':'docker','framework':'unittest','max_attempts':3})
        client=TestClient(create_platform_app(config,store))
        compact=client.get('/tasks/'+created['id']+'?details=false').json()
        full=client.get('/tasks/'+created['id']).json()
        assert compact['artifacts_loaded'] is False and 'artifacts_loaded' not in full
        assert compact['snapshot']['plan']==full['snapshot']['plan']
        assert client.get('/tasks?details=false').json()['tasks'][0]['artifacts_loaded'] is False
    finally:store.close()
