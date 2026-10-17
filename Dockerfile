# T060+T716: CPU slim server, non-root, healthchecked.
# Weights download on first run (cache /home/bouncer/.cache — bind-mount it).
FROM python:3.12-slim
WORKDIR /app
# T716: non-root user; the server binds 8000 (>1024), so no capabilities needed
RUN useradd --create-home --shell /usr/sbin/nologin bouncer
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src/ src/
# T719: self-test entrypoint — runs `bouncer check` before handing off to CMD
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# T717: volume mount points are pre-created and chowned so the named
# volumes inherit the non-root user's ownership on first use.
RUN pip install --no-cache-dir . \
    && python -c "import gatekeeper" \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /app/snapshots /home/bouncer/.cache \
    && chown -R bouncer:bouncer /app /home/bouncer/.cache
USER bouncer
ENV HOME=/home/bouncer
EXPOSE 8000
# T716: liveness against /health (T046) — /ready would flap while weights
# download on first run. T719: start-period covers the self-test plus the
# first boot's weight download into the (persistent) cache volume.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
# T719: self-test gate first, then the server process
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "gatekeeper.serve:app", "--host", "0.0.0.0", "--port", "8000"]
