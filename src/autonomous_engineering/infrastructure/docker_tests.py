"""Repository tests in a restricted, offline, ephemeral Linux container."""
import subprocess
import time
import threading
from pathlib import Path
from uuid import uuid4
from autonomous_engineering.domain.results import TestExecution


class DockerTestProcess:
    def __init__(self, settings, framework="unittest", cancel_event=None):
        self.config = settings
        self.framework = framework
        self.cancel_event = cancel_event

    def command(self, root, name):
        if ',' in str(root.resolve()):
            raise ValueError('Docker workspace paths cannot contain mount-option separators.')
        if self.framework not in {"unittest", "pytest", "npm"}:
            raise ValueError("Unsupported test framework")
        return [self.config.docker_executable, "run", "--rm", "--pull=never", "--name", name,
            "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=128", "--memory=512m", "--memory-swap=512m", "--cpus=1", "--user=10001:10001",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=268435456,mode=1777", "--log-driver=none",
            "--mount", f"type=bind,source={root.resolve()},target=/source,readonly",
            self.config.docker_image, self.framework]

    def run(self, root: Path):
        name = "ase-test-" + uuid4().hex
        command = self.command(root, name)
        started = time.monotonic()
        output = bytearray()
        overflow = threading.Event()
        timed_out, error = False, None
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if __import__('os').name == 'nt' else 0)
        except OSError:
            return TestExecution(command=tuple(command), exit_code=None, duration_seconds=time.monotonic()-started,
                output_summary="Docker could not start.", error="Docker executable is unavailable; host execution was not substituted.")
        def drain():
            while block := process.stdout.read(1024):
                remaining = 65536-len(output)
                output.extend(block[:max(remaining, 0)])
                if len(block) > remaining:
                    overflow.set()
        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        try:
            while process.poll() is None:
                timed_out = time.monotonic()-started >= self.config.test_timeout_seconds
                if timed_out or overflow.is_set() or self.cancel_event is not None and self.cancel_event.is_set():
                    error = "Output limit or cancellation ended execution." if not timed_out else None
                    break
                time.sleep(0.05)
        finally:
            # Removing the named container kills its entire isolated process tree.
            try:
                subprocess.run([self.config.docker_executable, "rm", "-f", name], stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                error = 'Container cleanup could not be confirmed; inspect Docker before running more tests.'
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            thread.join(timeout=2)
            if not thread.is_alive():
                process.stdout.close()
        text = bytes(output).decode('utf-8', errors='replace').strip()
        if len(text) > 3000:
            text = text[:1400] + '\n[output excerpt truncated]\n' + text[-1400:]
        if process.returncode in {125, 126, 127}:
            error = "Container failed to start. Start Docker and build/configure the runner image; host execution was not substituted."
        return TestExecution(command=tuple(command), exit_code=process.returncode, duration_seconds=time.monotonic()-started,
            output_summary=text or 'No output.', timed_out=timed_out, error=error)
