"""Optional compact HTTP projection; retained execution artifacts stay unchanged."""
from copy import deepcopy


def compact_job(item):
    if item is None: return None
    result = deepcopy(item)
    result['artifacts_loaded'] = False
    snapshot = result['snapshot']
    if snapshot.get('development'):
        snapshot['development']['diff'] = ''
        snapshot['development']['original_files'] = {}
    for record in snapshot.get('executions', []):
        record.pop('input_details', None)
        record.pop('output_details', None)
    for execution in (snapshot.get('tests') or {}).get('executions', []):
        execution['output_summary'] = ''
        execution.pop('evidence', None)
    return result
