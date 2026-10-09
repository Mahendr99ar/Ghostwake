FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY ghostwake ./ghostwake
RUN pip install --no-cache-dir .

ENV PORT=8000
EXPOSE 8000
# Fill the database once on boot, then serve. The pipeline is idempotent, so restarts are safe.
CMD python -m ghostwake.pipeline && uvicorn ghostwake.api.main:app --host 0.0.0.0 --port ${PORT}
