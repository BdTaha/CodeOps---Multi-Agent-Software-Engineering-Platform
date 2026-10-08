FROM python:3.12-slim
RUN mkdir /app && chown 10001:10001 /app
COPY containers/preview_runner.py /opt/codeops/preview_runner.py
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
WORKDIR /app
ENTRYPOINT ["python", "-I", "-B", "/opt/codeops/preview_runner.py"]
