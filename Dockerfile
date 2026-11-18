FROM node:24-bookworm-slim AS frontend
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.10-slim-bookworm
ARG INSTALL_RETRIEVAL=true
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MEDIGRAPH_DATA_DIR=/app/.runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements-runtime.txt requirements-ocr.txt requirements-retrieval.txt ./
RUN pip install --no-cache-dir -r requirements-ocr.txt && \
    if [ "$INSTALL_RETRIEVAL" = "true" ]; then \
      pip install --no-cache-dir torch==2.2.2 --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir -r requirements-retrieval.txt; fi
COPY backend/ ./backend/
COPY main.py ./
COPY --from=frontend /ui/dist ./frontend/dist/
RUN useradd --uid 10001 --create-home medigraph && mkdir -p /app/.runtime && chown -R medigraph:medigraph /app
USER medigraph
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
