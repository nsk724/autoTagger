FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --uid 1000 --create-home appuser \
 && mkdir /state && chown 1000:1000 /state
WORKDIR /app
COPY services/ticket-generator/requirements.txt .
RUN pip install -r requirements.txt \
 && pip uninstall -y setuptools wheel   # build-only tools from the base image, with known CVEs
# pulled with `dvc pull data/processed` before the build (Jenkins stage "Fetch data")
COPY data/processed/stream.parquet data/processed/heldout.parquet /app/data/
COPY services/ticket-generator/app ./app
USER 1000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import os, sys, time; sys.exit(time.time() - os.path.getmtime('/state/heartbeat') > 3 * float(os.environ.get('TICKET_INTERVAL_SECONDS', '15')))"
CMD ["python", "-m", "app.main"]
