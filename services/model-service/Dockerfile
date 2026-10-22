FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/tmp/hf
RUN useradd --uid 1000 --create-home appuser
WORKDIR /app
COPY services/model-service/requirements.txt .
RUN pip install -r requirements.txt \
 && pip uninstall -y setuptools wheel   # build-only tools from the base image, with known CVEs
COPY ml/triage_ml/text.py ./app/text.py
COPY services/model-service/app ./app
USER 1000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
