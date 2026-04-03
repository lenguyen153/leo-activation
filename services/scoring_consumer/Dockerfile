FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    confluent-kafka>=2.3.0 \
    redis>=5.0 \
    pydantic>=2.0 \
    pydantic-settings>=2.0 \
    python-dotenv>=1.0 \
    python-arango>=8.0 \
    "psycopg[binary]>=3.1" \
    prometheus_client>=0.20

# Copy project root modules needed for compute_incremental_score and resolve_ids
COPY agentic_tools/ /app/agentic_tools/
COPY data_utils/ /app/data_utils/
COPY main_configs.py /app/main_configs.py

# Copy shared + consumer
COPY services/__init__.py /app/services/__init__.py
COPY services/shared/ /app/services/shared/
COPY services/scoring_consumer/ /app/services/scoring_consumer/

# Ensure imports resolve from project root
ENV PYTHONPATH=/app

EXPOSE 8081

ENTRYPOINT ["python", "-m", "services.scoring_consumer.consumer"]
