"""Read-only review boundaries, local provider transport, and final outcomes."""

import json
from pathlib import Path

import pytest

from autonomous_engineering.agents.developer import Developer, approval_identity
from autonomous_engineering.agents.developer import DevelopmentProposal, NoDevelopmentChanges
from autonomous_engineering.agents.reviewer import html_source_facts, recommendation_is_unchanged
from autonomous_engineering.domain.results import ImplementationPlan
from autonomous_engineering.agents.reviewer import Reviewer, ReviewContext
from autonomous_engineering.agents.tester import Tester as AgentTester
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.results import ReviewResults
from autonomous_engineering.infrastructure.ollama_reviewer import OllamaReviewProvider
from autonomous_engineering.infrastructure.test_process import LocalTestProcess
from autonomous_engineering.tools.repository import RepositoryError
from autonomous_engineering.workflows.development import develop_approved
from autonomous_engineering.workflows.state import WorkflowUpdate
from test_developer import planned, FixtureDeveloper
from test_planner import ollama_server
from test_test_execution import suite


class FixtureReview:
    def __init__(self, result=None):
        self.context = None
        self.result = result if result is not None else {"approved": True, "summary": "Fixture: focused implementation and targeted tests.", "findings": []}

    def generate(self, context):
        self.context = context
        return self.result


@pytest.fixture
def developed(planned):
    state, storage, source = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    artifact = Developer(FixtureDeveloper()).develop(state, storage, approval_identity(state, storage))
    state = state.apply(WorkflowUpdate(changes=artifact.changes, development=artifact, development_attempt_increment=1))
    tests = AgentTester(LocalTestProcess()).run(state, storage)
    return state.apply(WorkflowUpdate(tests=tests)), storage, source


def test_review_receives_actual_full_source_diff_and_tests_and_never_writes(developed):
    state, storage, source = developed
    before = {p: p.read_bytes() for p in Path(state.workspace_path).rglob('*') if p.is_file()}
    provider = FixtureReview()
    result = Reviewer(provider).review(state, storage)
    assert result.approved
    assert provider.context.files['app.py'].endswith('name.strip()\n')
    assert provider.context.files['old.py'] is None
    assert 'tests/test_fixture.py' in provider.context.files
    assert provider.context.diff == state.development.diff
    assert provider.context.tests.executions[0].exit_code == 0
    assert before == {p: p.read_bytes() for p in Path(state.workspace_path).rglob('*') if p.is_file()}
    assert source.joinpath('app.py').read_text().endswith('+ name\n')


def finding(**overrides):
    return dict(severity='high', description='Fixture bug', recommended_fix='Fixture repair', file='app.py', line=2, evidence="return 'Hello ' + name.strip()", **overrides)


@pytest.mark.parametrize('result', [
    {'approved': True, 'summary': 'Contradictory', 'findings': [finding()]},
    {'approved': False, 'summary': 'No actionable findings', 'findings': []},
    {'approved': False, 'summary': 'Wrong path', 'findings': [{**finding(), 'file': 'unseen.py'}]},
    {'approved': False, 'summary': 'Wrong line', 'findings': [{**finding(), 'line': 999}]},
    {'approved': False, 'summary': 'Deleted line', 'findings': [{**finding(), 'file': 'old.py'}]},
    {'approved': False, 'summary': 'Traversal', 'findings': [{**finding(), 'file': '../host.py'}]},
    {'approved': False, 'summary': 'Uncited', 'findings': [{**finding(), 'file': None, 'line': None}]},
    {'approved': False, 'summary': 'Invented quote', 'findings': [{**finding(), 'evidence': 'not actual source'}]},
    {'approved': True, 'summary': 'Extra field', 'findings': [], 'fake_tests': 'passed'},
])
def test_invalid_or_ungrounded_decision_is_discarded(developed, result):
    state, storage, _ = developed
    with pytest.raises(RepositoryError) as error:
        Reviewer(FixtureReview(result)).review(state, storage)
    assert error.value.code == 'INVALID_REVIEW'


def test_tests_required_before_inference(planned):
    state, storage, _ = planned
    provider = FixtureReview()
    with pytest.raises(RepositoryError, match='passing test'):
        Reviewer(provider).review(state, storage)
    assert provider.context is None


def test_changed_code_after_development_cannot_be_reviewed(developed):
    state, storage, _ = developed
    Path(state.workspace_path, 'app.py').write_text('unexpected code\n')
    provider = FixtureReview()
    with pytest.raises(RepositoryError) as error:
        Reviewer(provider).review(state, storage)
    assert error.value.code == 'STALE_REVIEW'
    assert provider.context is None


def test_snapshot_change_during_inference_discards_review(developed):
    state, storage, _ = developed
    class Mutating(FixtureReview):
        def generate(self, context):
            Path(state.workspace_path, 'tests/test_fixture.py').write_text('# changed\n')
            return super().generate(context)
    with pytest.raises(RepositoryError) as error:
        Reviewer(Mutating()).review(state, storage)
    assert error.value.code == 'STALE_REVIEW'


def test_large_context_never_approves_truncated_evidence(developed):
    state, storage, _ = developed
    Path(state.workspace_path, 'tests/test_large.py').write_text('#' * 33000)
    provider = FixtureReview()
    with pytest.raises(RepositoryError) as error:
        Reviewer(provider).review(state, storage)
    assert error.value.code == 'REVIEW_CONTEXT_LIMIT'
    assert provider.context is None


def test_passing_tests_and_approved_review_allow_success(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    started = []
    result = develop_approved(state, storage, approval_identity(state, storage), FixtureDeveloper(),
        test_process=LocalTestProcess(), review_provider=FixtureReview(), on_node_started=started.append)
    assert started == ['develop_implementation', 'run_tests', 'review_changes', 'route_validation', 'finalize_development']
    assert result.task.status == result.report.outcome == 'succeeded'
    assert result.tests.outcome == 'passed' and result.review.approved
    assert [r.agent for r in result.executions] == ['developer', 'tester', 'reviewer', 'supervisor', 'supervisor']
    assert result.executions[2].duration_seconds >= 0
    assert not result.errors


def test_rejection_stops_with_findings_and_failed_record(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), '        self.assertTrue(True)\n')
    provider = FixtureReview({'approved': False, 'summary': 'Fixture rejection', 'findings': [finding()]})
    result = develop_approved(state, storage, approval_identity(state, storage), FixtureDeveloper(),
        test_process=LocalTestProcess(), review_provider=provider)
    assert result.task.status == 'failed' and not result.review.approved
    assert result.errors[-1].code == 'REVIEW_REJECTED'
    assert result.executions[2].status == 'failed'
    assert result.development_attempts == 1


@pytest.mark.parametrize('body,execute', [('        self.fail("Fixture")\n', True), ('        self.assertTrue(True)\n', False)])
def test_failed_or_skipped_tests_do_not_invoke_reviewer(planned, body, execute):
    state, storage, _ = planned
    suite(Path(state.workspace_path), body)
    provider = FixtureReview()
    result = develop_approved(state, storage, approval_identity(state, storage), FixtureDeveloper(),
        test_process=LocalTestProcess() if execute else None, review_provider=provider)
    assert provider.context is None and result.review is None
    assert result.task.status == 'failed'


def test_invalid_review_keeps_workflow_failed(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), '        self.assertTrue(True)\n')
    result = develop_approved(state, storage, approval_identity(state, storage), FixtureDeveloper(),
        test_process=LocalTestProcess(), review_provider=FixtureReview({'approved': True}))
    assert result.task.status == 'failed' and result.review is None
    assert result.errors[-1].code == 'INVALID_REVIEW'


def test_local_ollama_review_schema_and_evidence(developed, ollama_server):
    state, storage, _ = developed
    url, behavior, captured = ollama_server
    behavior['body'] = {'done': True, 'message': {'content': ReviewResults(approved=True, summary='Fixture approval').model_dump_json()}}
    provider = OllamaReviewProvider(Settings(_env_file=None, ollama_base_url=url, ollama_model='fixture-model'))
    assert Reviewer(provider).review(state, storage).approved
    body = captured[0][1]
    evidence = json.loads(body['messages'][1]['content'])
    context = ReviewContext.model_validate({**evidence,'task':state.task.request.model_dump()})
    assert body['format'] == provider.response_schema(context)
    finding_schema = body['format']['$defs']['ReviewFinding']
    assert finding_schema['properties']['file']['enum'] == list(context.files)
    assert set(('file', 'line', 'evidence')).issubset(finding_schema['required'])
    assert 'anyOf' not in finding_schema
    assert len(json.dumps(body['format'])) < 4000
    assert 'repository_path' not in evidence['task']
    assert evidence['tests']['executions'][0]['exit_code'] == 0
    assert evidence['diff'] == state.development.diff
    assert 'untrusted evidence' in body['messages'][0]['content']


@pytest.mark.parametrize('empty_response',[False,True])
@pytest.mark.parametrize('accept_recheck',[False,True])
def test_unchanged_repair_retains_artifact_and_rechecks_false_review(planned,empty_response,accept_recheck):
    state,storage,_ = planned
    state = state.apply(WorkflowUpdate(plan=ImplementationPlan(problem_interpretation='Fixture HTML',
        steps=({'description':'Create page','files':('page.html',)},),tests_to_run=('Run fixture tests',))))
    suite(Path(state.workspace_path),'        self.assertTrue(True)\n')
    html = '<html>\n<body>Hello</body>\n</html>\n'
    class Development:
        def generate(self,context):
            if context.attempt > 1 and empty_response:
                raise NoDevelopmentChanges('The closing tag exists at line 3.')
            return DevelopmentProposal(explanation='The closing tag exists at line 3.',edits=[dict(
                path='page.html',kind='created' if context.attempt==1 else 'modified',content=html,summary='Fixture page')])
    class Recheck:
        called = 0
        def generate(self,context):
            self.called += 1
            assert 'Explicit </html> end tag exists at line 3.' in context.source_facts['page.html']
            if self.called == 1 or not accept_recheck:
                return {'approved':False,'summary':'Missing closing </html> tag','findings':[dict(
                    severity='high',description='Missing closing tag',recommended_fix='Add closing tag',
                    file='page.html',line=1,evidence='<html>')]}
            assert 'Previous review: Missing closing </html> tag' in context.developer_repair_feedback
            return {'approved':True,'summary':'Rechecked the actual source; closing tag exists.','findings':[]}
    reviewer = Recheck()
    result = develop_approved(state,storage,approval_identity(state,storage),Development(),
        test_process=LocalTestProcess(),review_provider=reviewer,allow_repairs=True)
    assert result.task.status == ('succeeded' if accept_recheck else 'failed')
    assert result.development_attempts == (2 if accept_recheck else result.max_development_attempts)
    assert reviewer.called == result.development_attempts
    assert result.development and result.changes[0].kind == 'created'
    assert result.development.repair_note and result.tests.outcome == 'passed'
    assert not any(e.code=='INVALID_EDIT' for e in result.errors)
    assert Path(state.workspace_path,'page.html').read_text() == html


def test_html_facts_do_not_treat_comments_or_script_text_as_closing_tags():
    assert html_source_facts({'page.html':'<html><!-- </html> --><script>let x="</html>";</script>'}) == {'page.html':()}


def test_reviewer_cannot_claim_present_html_tag_is_missing(planned):
    state,storage,_ = planned
    state = state.apply(WorkflowUpdate(plan=ImplementationPlan(problem_interpretation='Fixture HTML',
        steps=({'description':'Create page','files':('page.html',)},),tests_to_run=('Run fixture',))))
    suite(Path(state.workspace_path),'        self.assertTrue(True)\n')
    class HTML:
        def generate(self,context):
            return DevelopmentProposal(explanation='Fixture',edits=[dict(path='page.html',kind='created',
                content='<html>\n<body>Hello</body>\n</html>\n',summary='Fixture')])
    artifact = Developer(HTML()).develop(state,storage,approval_identity(state,storage))
    state = state.apply(WorkflowUpdate(changes=artifact.changes,development=artifact))
    state = state.apply(WorkflowUpdate(tests=AgentTester(LocalTestProcess()).run(state,storage)))
    false_review = FixtureReview({'approved':False,'summary':'Missing closing tag','findings':[dict(severity='high',
        description='Missing closing </html> tag.',recommended_fix='Add </html>',file='page.html',line=3,evidence='</html>')]})
    with pytest.raises(RepositoryError) as error:
        Reviewer(false_review).review(state,storage)
    assert error.value.code == 'REVIEW_CONTRADICTION'


@pytest.mark.parametrize('recheck', ['approve', 'repeat', 'real_defect'])
@pytest.mark.parametrize('cite_html', [False, True])
def test_existing_css_repair_is_rechecked_without_edits_or_automatic_approval(planned, recheck, cite_html):
    state, storage, _ = planned
    state = state.apply(WorkflowUpdate(plan=ImplementationPlan(problem_interpretation='Hello in green',
        steps=({'description': 'Create page and styles', 'files': ('templates/index.html', 'static/css/style.css')},),
        tests_to_run=('Run fixture',))))
    css = 'h1#greeting {\n    color: green;\n    font-size: 2em;\n    text-align: center;\n}\n'
    html = '<html><head><link rel="stylesheet" href="static/css/style.css"></head>\n<body><h1 id="greeting">Hello</h1></body></html>\n'
    suite(Path(state.workspace_path), '        self.assertTrue(True)\n')
    artifact = Developer(FixtureDeveloper(edits=[
        dict(path='templates/index.html', kind='created', content=html, summary='Page'),
        dict(path='static/css/style.css', kind='created', content=css, summary='Styles'),
    ])).develop(state, storage, approval_identity(state, storage))
    state = state.apply(WorkflowUpdate(changes=artifact.changes, development=artifact))
    state = state.apply(WorkflowUpdate(tests=AgentTester(LocalTestProcess()).run(state, storage)))
    before = approval_identity(state, storage)
    false = dict(approved=False, summary='Missing green style', findings=[dict(
        severity='medium', description='Hello is not styled in green.',
        recommended_fix='Add the following CSS: ' + css, file='static/css/style.css', line=1, evidence='h1#greeting {')])
    if cite_html:
        false['findings'][0].update(file='templates/index.html', line=2, evidence='<h1 id="greeting">',
            recommended_fix="Add the following CSS to 'style.css':\n\n" + css)
    class Rechecking:
        contexts = []
        last_usage = None
        def generate(self, context):
            self.contexts.append(context)
            self.last_usage = dict(model='fixture', input_tokens=10, output_tokens=5)
            if len(self.contexts) == 1 or recheck == 'repeat':
                return false
            assert 'already exists verbatim' in context.review_validation_feedback
            if recheck == 'approve':
                return dict(approved=True, summary='Fixture recheck approval', findings=[])
            return dict(approved=False, summary='Incorrect stylesheet path when opened directly', findings=[dict(
                severity='medium', description='Opening templates/index.html directly resolves the stylesheet under templates/static/, not static/.',
                recommended_fix='For direct static viewing, change href to ../static/css/style.css.',
                file='templates/index.html', line=1, evidence='href="static/css/style.css"')])
    provider = Rechecking()
    if recheck == 'repeat':
        with pytest.raises(RepositoryError) as error:
            Reviewer(provider).review(state, storage)
        assert error.value.code == 'REVIEW_CONTRADICTION'
    else:
        decision = Reviewer(provider).review(state, storage)
        assert decision.approved == (recheck == 'approve')
        assert decision.summary.startswith('After evidence recheck:')
    assert len(provider.contexts) == 2
    assert provider.contexts[0].review_validation_feedback is None
    assert provider.last_usage == dict(model='fixture', input_tokens=20, output_tokens=10)
    assert approval_identity(state, storage) == before


@pytest.mark.parametrize('recommendation, content, unchanged', [
    ('Add this code:\n```css\nh1 {\n color: green;\n}\n```', 'h1 {\n color: green;\n}\n', True),
    ('Add this code:\n```css\nh1 {\n color: green;\n}\n```', 'h1 {\n color: red;\n}\n', False),
    ('Remove this code:\n```css\nh1 {\n color: green;\n}\n```', 'h1 {\n color: green;\n}\n', False),
    ('Move this code:\n```css\nh1 {\n color: green;\n}\n```', 'h1 {\n color: green;\n}\n', False),
    ('Replace with:\n```python\nif ok:\n  run()\nfinish()\n```', 'if ok:\n  run()\n  finish()\n', False),
    ('Use this:\n```python\nx = "a  b"\ny = 2\n```', 'x = "a b"\ny = 2\n', False),
    ('Add this code:\n```css\nh1 {\n color: green;\n}\n```', '/*\nh1 {\n color: green;\n}\n*/\n', False),
    ('Add this code:\n```python\nx = 1\ny = 2\n```', 'def existing():\n    x = 1\n    y = 2\n', False),
])
def test_no_change_recommendations_preserve_code_semantics(recommendation, content, unchanged):
    assert recommendation_is_unchanged(recommendation, content) == unchanged


def test_stale_review_is_never_retried_even_when_decision_is_invalid(developed):
    state, storage, _ = developed
    class Mutating:
        called = 0
        def generate(self, context):
            self.called += 1
            Path(state.workspace_path, 'app.py').write_text('changed\n')
            return {'approved': True}
    provider = Mutating()
    with pytest.raises(RepositoryError) as error:
        Reviewer(provider).review(state, storage)
    assert error.value.code == 'STALE_REVIEW'
    assert provider.called == 1
