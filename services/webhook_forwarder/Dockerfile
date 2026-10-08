FROM python:3.11-slim

WORKDIR /app

# Install dependencies (websockets/psycopg/arango needed because scrub_pii is
# imported from the ws_forwarder module to keep the payload contract identical)
RUN pip install --no-cache-dir \
    confluent-kafka>=2.3.0 \
    httpx>=0.27 \
    pydantic>=2.0 \
    pydantic-settings>=2.0 \
    websockets>=13.0 \
    structlog>=24.0 \
    prometheus_client>=0.20 \
    psycopg[binary]>=3.1 \
    python-arango>=7.0 \
    python-dotenv>=1.0

# Copy shared + forwarders + data_utils
COPY services/__init__.py /app/services/__init__.py
COPY services/shared/ /app/services/shared/
COPY services/ws_forwarder/ /app/services/ws_forwarder/
COPY services/webhook_forwarder/ /app/services/webhook_forwarder/
COPY data_utils/ /app/data_utils/

# Ensure imports resolve from project root
ENV PYTHONPATH=/app

EXPOSE 8083

ENTRYPOINT ["python", "-m", "services.webhook_forwarder.consumer"]
