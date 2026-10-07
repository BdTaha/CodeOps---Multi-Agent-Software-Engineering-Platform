FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==9.1.1
COPY containers/runner.py /opt/ase/runner.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
USER 10001:10001
ENTRYPOINT ["python", "-I", "-B", "/opt/ase/runner.py"]
