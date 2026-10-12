# T060: CPU slim server. Weights download on first run (cache /root/.cache).
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir -e ".[dev]" fastapi uvicorn && python -c "import gatekeeper"
EXPOSE 8000
CMD ["uvicorn", "gatekeeper.serve:app", "--host", "0.0.0.0", "--port", "8000"]
