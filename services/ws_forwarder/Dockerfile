FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    confluent-kafka>=2.3.0 \
    pydantic>=2.0 \
    websockets>=13.0 \
    structlog>=24.0 \
    prometheus_client>=0.20

# Copy shared + forwarder
COPY services/__init__.py /app/services/__init__.py
COPY services/shared/ /app/services/shared/
COPY services/ws_forwarder/ /app/services/ws_forwarder/

# Ensure imports resolve from project root
ENV PYTHONPATH=/app

EXPOSE 8082

ENTRYPOINT ["python", "-m", "services.ws_forwarder.consumer"]
