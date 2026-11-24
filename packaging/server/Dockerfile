# 3.14 JARVIS nonstop (návrh 2): the core on an always-on box at home – mini PC, Raspberry Pi 5 (arm64), NAS with Docker.
# The phone, the house satellites, the wall display and your PCs connect to it; it runs when the PC is off.
# Build from the repository root:  docker build -f packaging/server/Dockerfile -t jarvis-server .
FROM node:22-slim AS web
WORKDIR /src/web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 JARVIS_HOME=/data PIP_NO_CACHE_DIR=1 JARVIS_WEB_DIST=/app/web/dist
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY core/ ./core/
COPY --from=web /src/web/dist ./web/dist
RUN pip install ./core && useradd -m jarvis && mkdir -p /data && chown jarvis /data
USER jarvis
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4)" || exit 1
CMD ["python", "-m", "jarvis", "--no-ui", "--no-voice"]
