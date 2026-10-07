"""GitHub import and explicitly requested draft PR delivery via official REST API."""
import base64
import json
import re
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
from uuid import uuid4

from autonomous_engineering.infrastructure.ollama import NoRedirect
from autonomous_engineering.infrastructure.delivery import checked_artifact
from autonomous_engineering.tools.repository import RepositoryError, excluded
from autonomous_engineering.domain.base import repository_relative_path


class GitHub:
    def __init__(self, token=None):
        self.token = token

    def call(self, method, path, body=None):
        headers = {'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2026-03-10', 'User-Agent':'Engineering-Lab'}
        if self.token:
            headers['Authorization'] = 'Bearer '+self.token
        request = Request('https://api.github.com'+path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=30) as response:
                data = response.read(8*1024*1024+1)
        except (HTTPError, URLError, OSError) as exc:
            if isinstance(exc, HTTPError):
                code = exc.code
                exc.close()
            else:
                code = None
            raise RepositoryError('GITHUB_FAILED', f'GitHub request failed (HTTP {code or "unavailable"}); check credentials, permissions and rate limits.') from exc
        if len(data) > 8*1024*1024:
            raise RepositoryError('GITHUB_LIMIT', 'GitHub response exceeds the bounded import limit.')
        return json.loads(data)

    @staticmethod
    def slug(value):
        value = value.removeprefix('https://github.com/').removesuffix('.git').strip('/')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',value):
            raise RepositoryError('GITHUB_REPOSITORY', 'Use a GitHub owner/repository name or its HTTPS repository URL.')
        return value

    def import_repository(self, value, branch, root):
        slug = self.slug(value)
        repo = self.call('GET','/repos/'+slug)
        branch = branch or repo['default_branch']
        commit = self.call('GET','/repos/'+slug+'/commits/'+quote(branch,safe=''))
        base = commit['sha']
        tree = self.call('GET','/repos/'+slug+'/git/trees/'+commit['commit']['tree']['sha']+'?recursive=1')
        if tree.get('truncated') or len(tree['tree']) > 20000:
            raise RepositoryError('GITHUB_LIMIT','Repository tree is too large for this bounded text importer.')
        target = root.resolve() / 'imported' / (slug.replace('/','-')+'-'+uuid4().hex[:8])
        contents, total = {}, 0
        for item in tree['tree']:
            if item['type'] != 'blob' or item.get('mode') == '120000' or item.get('size',0) > 262144:
                continue
            path = repository_relative_path(item['path'])
            parts = Path(path).parts
            if any(excluded(Path(p),directory=i<len(parts)-1) for i,p in enumerate(parts)):
                continue
            blob = self.call('GET','/repos/'+slug+'/git/blobs/'+item['sha'])
            try:
                raw = base64.b64decode(blob['content'])
                text = raw.decode('utf-8')
                if '\x00' in text:
                    continue
            except (ValueError, UnicodeDecodeError):
                continue
            total += len(raw)
            if total > 16777216 or len(contents) >= 2000:
                raise RepositoryError('GITHUB_LIMIT','Repository text exceeds the bounded snapshot limits.')
            contents[path] = text
        from autonomous_engineering.tools.repository import is_link
        for component in (*reversed(target.parents),target):
            if component.exists() and is_link(component):
                raise RepositoryError('PATH_DENIED','Import storage cannot traverse links.')
        target.mkdir(parents=True,exist_ok=False)
        from autonomous_engineering.tools.repository import RepositoryReader
        from autonomous_engineering.tools.workspace_changes import checked_target
        reader = RepositoryReader(target)
        for path,text in contents.items():
            out = checked_target(reader,path)
            out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(text,encoding='utf-8',newline='')
        return target, {'name':slug, 'description':'Imported GitHub text snapshot', 'stack':[],
            'github':{'slug':slug,'base':branch,'base_sha':base}}

    def publish(self, state, config, project):
        if not self.token:
            raise RepositoryError('GITHUB_NOT_CONFIGURED','Set ASE_GITHUB_TOKEN before draft PR delivery.')
        source = project.get('github')
        if source is None:
            raise RepositoryError('GITHUB_ORIGIN_REQUIRED','Import this repository from GitHub before publishing its changes.')
        reader = checked_artifact(state,config.workspace_root)
        slug, base = source['slug'], source['base']
        prefix = '/repos/'+slug
        head = self.call('GET',prefix+'/commits/'+quote(base,safe=''))
        if head['sha'] != source['base_sha']:
            raise RepositoryError('GITHUB_BASE_CHANGED','GitHub base branch moved since import; re-import and rerun before publishing.')
        items = []
        for change in state.changes:
            if change.kind == 'deleted':
                items.append({'path':change.path,'mode':'100644','type':'blob','sha':None})
            else:
                content = reader.read_text(change.path)
                blob = self.call('POST',prefix+'/git/blobs',{'content':content,'encoding':'utf-8'})
                items.append({'path':change.path,'mode':'100644','type':'blob','sha':blob['sha']})
        tree = self.call('POST',prefix+'/git/trees',{'base_tree':head['commit']['tree']['sha'],'tree':items})
        branch = 'ase/'+str(state.task.task_id)
        try:
            existing = self.call('GET',prefix+'/git/ref/heads/'+quote(branch,safe='/'))
        except RepositoryError as exc:
            if 'HTTP 404' not in str(exc):
                raise
            existing = None
        if existing:
            previous = self.call('GET',prefix+'/git/commits/'+existing['object']['sha'])
            if previous['tree']['sha'] != tree['sha']:
                raise RepositoryError('GITHUB_BRANCH_EXISTS','Delivery branch already contains different changes; refusing to overwrite it.')
        else:
            commit = self.call('POST',prefix+'/git/commits',{'message':state.task.request.user_request[:200],
                'tree':tree['sha'],'parents':[head['sha']]})
            self.call('POST',prefix+'/git/refs',{'ref':'refs/heads/'+branch,'sha':commit['sha']})
        owner = slug.split('/')[0]
        existing_prs = self.call('GET',prefix+'/pulls?state=all&head='+quote(owner+':'+branch,safe='')+'&base='+quote(base,safe=''))
        if existing_prs:
            return {'url':existing_prs[0]['html_url'],'branch':branch}
        body = state.report.summary+'\n\nValidation: '+state.tests.summary+'\n\nModel review: '+state.review.summary+'\n\n'+ '\n'.join(state.report.limitations)
        pr = self.call('POST',prefix+'/pulls',{'title':state.task.request.user_request[:200],'head':branch,
            'base':base,'body':body,'draft':True})
        return {'url':pr['html_url'],'branch':branch}
