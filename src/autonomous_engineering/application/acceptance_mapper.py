"""Read-only mapping of final artifacts; no tests, reviews or code mutation."""
import ast
import re
from collections import Counter
from autonomous_engineering.agents.developer import workspace_reader
from autonomous_engineering.domain.acceptance_evidence import EvidenceSource, EvidenceMapping

def normalized(text):
    return ' '.join(text.casefold().split()).rstrip('.')

def explicit_match(criterion, identifier, docstring=''):
    # Deliberately no fuzzy token overlap, synonym guesses or aggregate passes.
    return (bool(re.search(r'(?<![\w])'+re.escape(identifier)+r'(?![\w])',criterion.description))
        and not re.search(r'\b(fail|fails|failed|failing|not pass|must not run|should not run)\b',criterion.description,re.I)
        or bool(docstring and normalized(docstring)==normalized(criterion.description)))

def artifact_sources(state, storage, criteria):
    reader = workspace_reader(state, storage)
    inventory = set(reader.inventory().files)
    sources = []
    test_methods = {}
    for path in sorted(inventory):
        if not (path.startswith('tests/') and path.endswith('.py')): continue
        try: tree=ast.parse(reader.read_text(path))
        except SyntaxError: continue
        module=path[6:-3].replace('/','.')
        for cls in (node for node in tree.body if isinstance(node,ast.ClassDef)):
            for method in cls.body:
                if not isinstance(method,ast.FunctionDef) or not method.name.startswith('test'): continue
                has_assertion=any(isinstance(n,ast.Assert) or isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr.startswith('assert') for n in ast.walk(method))
                if has_assertion:
                    test_methods[f'{module}.{cls.name}.{method.name}']=(path,method.name,ast.get_docstring(method) or '')
    if state.tests and state.tests.outcome=='passed':
        for index, execution in enumerate(state.tests.executions):
            if execution.exit_code!=0 or execution.error or execution.timed_out: continue
            if not any('unittest' in part for part in execution.command): continue
            matches=[]
            lines=execution.output_summary.splitlines()
            for line_number,line in enumerate(lines,1):
                match=re.fullmatch(r'(test\w*) \(([\w.]+)\) \.\.\. (ok|FAIL|ERROR|skipped .+)',line)
                # unittest prints a test's first docstring line before its result.
                header=re.fullmatch(r'(test\w*) \(([\w.]+)\)',line)
                if header and header.group(2) in test_methods and line_number<len(lines):
                    doc=test_methods[header.group(2)][2].splitlines()
                    if doc and lines[line_number]==doc[0]+' ... ok':
                        match=re.fullmatch(r'(test\w*) \(([\w.]+)\) \.\.\. (ok)',line+' ... ok')
                if match: matches.append((match,line_number))
            counts=Counter(match.group(2) for match,_ in matches)
            for match,line_number in matches:
                identifier=match.group(2)
                if counts[identifier]!=1 or identifier not in test_methods or match.group(3)!='ok': continue
                path,name,docstring=test_methods[identifier]
                explicit=tuple(c.id for c in criteria if explicit_match(c,name,docstring) or explicit_match(c,identifier))
                sources.append(EvidenceSource(id=f'test:{index}:{identifier}',evidence_type='automated_test',
                    reference=dict(artifact='tests',execution_index=index,output_line=line_number,framework='unittest',
                        test_identifier=identifier,test_file=path,outcome='passed'),
                    summary=f'{identifier} — passed in the retained unittest result.',executed=True,explicit_criteria=explicit))
    for index, change in enumerate(state.changes):
        # Deleted files exist in the canonical diff/original-files manifest.
        if change.path not in inventory and not (state.development and change.kind=='deleted' and change.path in state.development.original_files):
            raise ValueError('Changed-file reference is absent from final artifacts.')
        sources.append(EvidenceSource(id=f'change:{index}',evidence_type='code_change',
            reference=dict(artifact='development',change_index=index,file=change.path,kind=change.kind.value),
            summary=change.summary,explicit_criteria=tuple(c.id for c in criteria if change.path in c.description or normalized(c.description)==normalized(change.summary))))
    if state.review:
        for index,finding in enumerate(state.review.findings):
            if finding.file and finding.file not in inventory and not (state.development and finding.file in state.development.original_files):
                raise ValueError('Reviewer file reference is absent from final artifacts.')
            sources.append(EvidenceSource(id=f'review:{index}',evidence_type='reviewer',negative=True,
                reference=dict(artifact='review',finding_index=index,file=finding.file,line=finding.line,severity=finding.severity.value),
                summary=finding.description,explicit_criteria=tuple(c.id for c in criteria if normalized(c.description) in normalized(finding.description))))
        # A requirement-specific excerpt of the canonical summary can support it;
        # generic approval never becomes a source for all criteria.
        for criterion in criteria:
            if normalized(criterion.description) in normalized(state.review.summary):
                sources.append(EvidenceSource(id=f'review-summary:{criterion.id}',evidence_type='reviewer',
                    reference=dict(artifact='review',field='summary'),summary=state.review.summary,
                    explicit_criteria=(criterion.id,)))
        if len(state.review.summary.split())>=8 and not any(source.id.startswith('review-summary:') for source in sources):
            sources.append(EvidenceSource(id='review-summary',evidence_type='reviewer',
                reference=dict(artifact='review',field='summary'),summary=state.review.summary))
    return tuple(sources)

def map_evidence(criteria, sources, proposal=None):
    ids={str(c.id) for c in criteria}; indexed={s.id:s for s in sources}
    associations={str(c.id):{} for c in criteria}
    for source in sources:
        for criterion_id in source.explicit_criteria:
            if str(criterion_id) not in ids: raise ValueError('Unknown criterion reference.')
            associations[str(criterion_id)][source.id]='deterministic'
    if proposal is not None:
        proposal=EvidenceMapping.model_validate(proposal)
        for item in proposal.associations:
            if str(item.criterion_id) not in ids or item.source_id not in indexed:
                raise ValueError('Evidence mapper referenced an unknown criterion or source.')
            associations[str(item.criterion_id)].setdefault(item.source_id,'semantic')
    # Never hide a final reviewer concern merely because the mapper could not
    # determine its scope. Conservative unresolved applicability for every row.
    for source in sources:
        if source.negative and not source.explicit_criteria:
            for values in associations.values(): values.setdefault(source.id,'unresolved_scope')
    results=[]
    for criterion in criteria:
        selected=[(indexed[key],mapping) for key,mapping in associations[str(criterion.id)].items()]
        conflict=any(source.negative for source,_ in selected)
        verified=any(source.executed and not source.negative and mapping=='deterministic' for source,mapping in selected)
        status='unverified' if conflict or not selected else 'verified' if verified else 'supported'
        results.append(dict(criterion=criterion,status=status,conflict=conflict,sources=selected))
    return results
