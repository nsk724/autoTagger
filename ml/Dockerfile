FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/ml HF_HOME=/tmp/hf
# git: DVC needs it inside the Jenkins workspace
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 1000 --create-home appuser
COPY ml/requirements.txt /opt/ml/requirements.txt
RUN pip install -r /opt/ml/requirements.txt
COPY ml/triage_ml /opt/ml/triage_ml
RUN mkdir -p /tmp/hf && chown 1000:1000 /tmp/hf
USER 1000
# Jenkins runs the tools from its workspace (repo checkout): data/ and config/ are read from there
CMD ["python", "-c", "import triage_ml"]
