"""Bounded trusted-local Python tests. This adapter is not an OS sandbox."""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from autonomous_engineering.domain.results import TestExecution

# A fixed bootstrap, never a command supplied by the repository or an LLM.
BOOTSTRAP = """import sys, unittest
sys.path.insert(0, '.')
suite = unittest.defaultTestLoader.discover('tests', pattern='test*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(5 if result.testsRun == 0 else 0 if result.wasSuccessful() else 1)
"""


class LocalTestProcess:
    def __init__(self, timeout_seconds: float = 60, output_limit: int = 65536, framework="unittest", cancel_event=None):
        if not 0 < timeout_seconds <= 300 or not 1024 <= output_limit <= 1048576:
            raise ValueError("Invalid test execution bounds")
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit
        if framework not in {"unittest", "pytest"}:
            raise ValueError("Local execution supports unittest or pytest")
        self.framework = framework
        self.cancel_event = cancel_event

    def run(self, root: Path) -> TestExecution:
        bootstrap = BOOTSTRAP if self.framework == "unittest" else "import sys, pytest; sys.path.insert(0, '.'); sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', 'tests']))"
        command = (sys.executable, "-I", "-B", "-c", bootstrap)
        started = time.monotonic()
        # Do not inherit API keys, provider settings, PYTHONPATH, or user plugins.
        env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP") if name in os.environ}
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        captured = bytearray()
        overflow = threading.Event()
        timed_out = False
        error = None
        try:
            process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt")
        except OSError:
            return TestExecution(command=command, exit_code=None, duration_seconds=time.monotonic() - started,
                output_summary="Test process could not start.", error="The configured Python interpreter could not launch tests.")

        def drain():
            assert process.stdout is not None
            while block := process.stdout.read(1024):
                remaining = self.output_limit - len(captured)
                captured.extend(block[:max(remaining, 0)])
                if len(block) > remaining:
                    overflow.set()

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        while process.poll() is None:
            timed_out = time.monotonic() - started >= self.timeout_seconds
            if timed_out or overflow.is_set() or self.cancel_event is not None and self.cancel_event.is_set():
                if self.cancel_event is not None and self.cancel_event.is_set():
                    error = "Cancellation ended test execution."
                self._stop(process)
                break
            time.sleep(0.02)
        process.wait()
        reader.join(timeout=1)
        if reader.is_alive():
            # A descendant may still hold the pipe after its parent exited.
            self._stop(process)
            reader.join(timeout=1)
            error = "Test descendants retained the output pipe; execution is incomplete."
        if overflow.is_set():
            error = "Test output exceeded the configured byte limit; execution was stopped."
        if not reader.is_alive() and process.stdout is not None:
            process.stdout.close()
        output = bytes(captured).decode("utf-8", errors="replace").strip()
        if len(output) > 3000:
            output = output[:1400] + "\n[output excerpt truncated]\n" + output[-1400:]
        return TestExecution(command=command, exit_code=process.returncode,
            duration_seconds=time.monotonic() - started, output_summary=output or "No test output was produced.",
            timed_out=timed_out, error=error)

    @staticmethod
    def _stop(process: subprocess.Popen):
        if os.name == "nt":
            killer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            subprocess.run([str(killer), "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
