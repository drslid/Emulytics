FROM node:22-bookworm-slim AS chatgpt-runtime
WORKDIR /codex-install
COPY codex-runtime/package.json codex-runtime/package-lock.json ./
RUN npm install --global --ignore-scripts --no-audit --no-fund npm@10.9.4 \
    && npm ci --ignore-scripts --no-audit --no-fund \
    && mkdir /opt/chatgpt-runtime \
    && cp node_modules/@openai/codex-linux-*/vendor/*/bin/codex* /opt/chatgpt-runtime/

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends aapt \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock ./
RUN python -m pip install --no-cache-dir --upgrade pip==26.3 \
    && python -m pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app
COPY --from=chatgpt-runtime /opt/chatgpt-runtime/ /usr/local/bin/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]

