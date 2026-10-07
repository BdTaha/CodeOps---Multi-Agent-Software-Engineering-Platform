"""Trusted image entrypoint. Copy read-only source into bounded ephemeral storage."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

shutil.copytree('/source', '/tmp/work')
os.chdir('/tmp/work')
sys.path.insert(0, '/tmp/work')
framework = sys.argv[1]
if framework == 'unittest':
    suite = unittest.defaultTestLoader.discover('tests', pattern='test*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(5 if result.testsRun == 0 else 0 if result.wasSuccessful() else 1)
elif framework == 'pytest':
    import pytest
    sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', 'tests']))
elif framework == 'npm':
    # Image must include Node and dependencies. No install/network during a test.
    sys.exit(subprocess.call(['npm', 'test'], env={**os.environ, 'CI': 'true'}))
else:
    sys.exit('Unsupported framework')
