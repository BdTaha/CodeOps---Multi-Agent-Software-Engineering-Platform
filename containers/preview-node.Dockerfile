FROM node:22-bookworm-slim
RUN mkdir /app && chown 10001:10001 /app
COPY containers/preview_runner.mjs /opt/codeops/preview_runner.mjs
ENV HOME=/tmp NODE_ENV=development
USER 10001:10001
WORKDIR /app
ENTRYPOINT ["node", "/opt/codeops/preview_runner.mjs"]
