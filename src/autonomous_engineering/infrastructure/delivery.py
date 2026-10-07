"""Explicit, integrity-checked local application and Git commit exports."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
from uuid import UUID

from autonomous_engineering.agents.developer import workspace_reader
from autonomous_engineering.domain.development import DevelopmentProposal, FileEdit
from autonomous_engineering.tools.repository import RepositoryReader, RepositoryError
from autonomous_engineering.tools.workspace_changes import checked_target, apply_edits


def checked_artifact(state, storage):
    if state.task.status != 'succeeded' or state.development is None or state.review is None or not state.review.approved:
        raise RepositoryError('DELIVERY_DENIED', 'Delivery requires a tested, reviewed successful snapshot.')
    reader = workspace_reader(state, storage)
    if not state.changes:
        raise RepositoryError('DELIVERY_DENIED', 'No reviewed changes are available for delivery.')
    present = reader.inventory().files
    for change in state.changes:
        text = reader.read_text(change.path) if change.path in present else None
        actual = hashlib.sha256(text.encode()).hexdigest() if text is not None else None
        if actual != state.development.content_hashes.get(change.path):
            raise RepositoryError('STALE_DELIVERY', 'Snapshot changed after review; delivery was refused.')
    return reader


def receipt(state, storage):
    checked_artifact(state, storage)
    return hashlib.sha256(json.dumps({'task':str(state.task.task_id), 'artifact':state.development.model_dump(mode='json')}, sort_keys=True).encode()).hexdigest()


def apply_original(state, config):
    snapshot = checked_artifact(state, config.workspace_root)
    source = Path(state.task.request.repository_path).resolve()
    if not source.is_relative_to(config.repository_root.resolve()):
        raise RepositoryError('SOURCE_DENIED', 'Source lies outside the configured repository root.')
    reader = RepositoryReader(source)
    originals = state.development.original_files
    edits, files = [], {}
    current = reader.inventory().files
    final = snapshot.inventory().files
    for change in state.changes:
        before = reader.read_text(change.path) if change.path in current else None
        if change.path not in originals or before != originals[change.path]:
            raise RepositoryError('SOURCE_CHANGED', 'Original files changed since planning; do not overwrite new work.')
        after = snapshot.read_text(change.path) if change.path in final else None
        files[change.path] = before
        edits.append(FileEdit(path=change.path, kind=change.kind, content=after, summary=change.summary))
    diff, changes = apply_edits(reader, DevelopmentProposal(explanation='Explicitly approved source application', edits=tuple(edits)), files)
    return {'applied_files':[c.path for c in changes], 'diff':diff}


def export_commit(state, config):
    reader = checked_artifact(state, config.workspace_root)
    target = config.workspace_root.resolve() / 'exports' / str(UUID(str(state.task.task_id)))
    # Independent export; source and managed execution snapshot remain untouched.
    if target.exists():
        raise RepositoryError('EXPORT_EXISTS', 'A commit export already exists for this task.')
    target = checked_target(RepositoryReader(config.workspace_root.resolve()), 'exports/' + str(state.task.task_id))
    target.mkdir(parents=True)
    final = {name:reader.read_text(name) for name in reader.inventory().files}
    baseline = {**final}
    for path, content in state.development.original_files.items():
        if content is None:
            baseline.pop(path, None)
        else:
            baseline[path] = content
    for path, content in baseline.items():
        out = target / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding='utf-8', newline='')
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    def git(*args):
        result = subprocess.run(['git','-c','core.hooksPath='+str(target / 'disabled-hooks'),'-c','user.name=Engineering Lab',
            '-c','user.email=engineering-lab@localhost',*args], cwd=target, env=env, capture_output=True, timeout=30)
        if result.returncode:
            raise RepositoryError('GIT_FAILED', 'Git export failed; inspect the retained export, without modifying the original repository.')
        return result.stdout.decode().strip()
    git('init','-b','ase/'+str(state.task.task_id))
    git('add','--all')
    git('commit','--allow-empty','-m','Baseline filtered source snapshot')
    export_reader = RepositoryReader(target)
    for change in state.changes:
        out = checked_target(export_reader, change.path)
        if change.path not in final:
            out.unlink(missing_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(final[change.path], encoding='utf-8', newline='')
    git('add','--all')
    git('commit','--allow-empty','-m',state.task.request.user_request[:200].replace('\n',' '))
    commit = git('rev-parse','HEAD')
    archive = target.parent / (str(state.task.task_id)+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
        for path in target.rglob('*'):
            if path.is_file() and not path.is_symlink():
                output.write(path, str(path.relative_to(target)))
    return {'commit':commit, 'archive':str(archive), 'export_path':str(target)}
