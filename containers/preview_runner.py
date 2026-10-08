"""Trusted bootstrap: only argv, dependency writes live in the disposable volume."""
import json
import os
import subprocess
import sys

profile=json.loads(sys.argv[2])
os.environ.update(profile['environment'])
os.environ['PATH']='/app/.preview-deps/bin:'+os.environ['PATH']
os.environ['PYTHONPATH']='/app/.preview-deps/lib/python3.12/site-packages:/app'
if sys.argv[1]=='build':
    if os.path.isfile('requirements.txt'):
        subprocess.run(['python','-m','venv','/app/.preview-deps'],check=True)
        subprocess.run(['/app/.preview-deps/bin/pip','install','--disable-pip-version-check','-r','requirements.txt'],check=True)
    for command in profile['build_commands']: subprocess.run(command,check=True)
else:
    os.execvpe(profile['start_command'][0],profile['start_command'],os.environ)
