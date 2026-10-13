# The inventory server (+ the printd agent, same image) for running on any
# Docker host. Built from the repo root by docker/compose.yaml:
#   docker build -f docker/Dockerfile .

FROM node:22-bookworm-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
# DejaVu Sans Bold is the label font labels.py looks for first.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY server /src/server
COPY printd /src/printd
RUN pip install --no-cache-dir "/src/server[embed,claude]" /src/printd \
    && rm -rf /src
COPY --from=web /src/web/dist /opt/inventory/web

ENV PYTHONUNBUFFERED=1 \
    INVENTORY_DATA_DIR=/data \
    INVENTORY_WEB_DIR=/opt/inventory/web \
    INVENTORY_HOST=0.0.0.0 \
    INVENTORY_PORT=8080 \
    INVENTORY_PRINTD_URL=http://127.0.0.1:8631
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/status', timeout=4)"
CMD ["inventory-server"]
