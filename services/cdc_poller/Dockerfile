FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Install only the dependencies needed for CDC poller
RUN pip install --no-cache-dir \
    confluent-kafka>=2.3.0 \
    redis>=5.0 \
    requests>=2.31 \
    pydantic>=2.0 \
    python-arango>=8.0 \
    prometheus_client>=0.20

# Copy shared module and poller
COPY services/shared/ /app/services/shared/
COPY services/__init__.py /app/services/__init__.py
COPY services/cdc_poller/ /app/services/cdc_poller/

EXPOSE 8080

ENTRYPOINT ["python", "-m", "services.cdc_poller.poller"]
