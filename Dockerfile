# T060+T716: CPU slim server, non-root, healthchecked.
# Weights download on first run (cache /home/bouncer/.cache — bind-mount it).
FROM python:3.12-slim
WORKDIR /app
# T716: non-root user; the server binds 8000 (>1024), so no capabilities needed
RUN useradd --create-home --shell /usr/sbin/nologin bouncer
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src/ src/
RUN pip install --no-cache-dir . \
    && python -c "import gatekeeper" \
    && chown -R bouncer:bouncer /app
USER bouncer
ENV HOME=/home/bouncer
EXPOSE 8000
# T716: liveness against /health (T046) — /ready would flap while weights
# download on first run; start-period covers the slow cold start anyway.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
CMD ["uvicorn", "gatekeeper.serve:app", "--host", "0.0.0.0", "--port", "8000"]
