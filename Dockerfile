FROM node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94 AS web
WORKDIR /build
COPY app/web/package.json app/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/web/src ./src
COPY app/web/tsconfig.json app/web/vite.config.ts app/web/index.html app/web/simulator.html ./
RUN npm run build

FROM python:3.13.9-slim-bookworm@sha256:b685a4fa58bb19d1814d78a1ec0f0208f351452724f78b20212c984d6e124a34
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/platform/app/src:/opt/platform/app EP_BIND=0.0.0.0 LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false HAYSTACK_TELEMETRY_ENABLED=false OTEL_SDK_DISABLED=true
WORKDIR /opt/platform
COPY app/requirements/enterprise-core.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
COPY app/src ./app/src
COPY app/resources ./app/resources
COPY app/agents ./app/agents
COPY app/skills ./app/skills
COPY app/enterprise_skills ./app/enterprise_skills
COPY app/process-packs ./app/process-packs
COPY app/LICENSE app/NOTICE app/THIRD_PARTY_NOTICES.md ./app/
COPY LICENSE NOTICE ./
COPY deploy/container_entry.py ./deploy/container_entry.py
COPY --from=web /build/dist ./app/web/dist
USER 10001:10001
EXPOSE 8774
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8774/api/health',timeout=3)"
ENTRYPOINT ["python","deploy/container_entry.py"]
