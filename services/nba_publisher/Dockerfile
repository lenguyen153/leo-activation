FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    confluent-kafka>=2.3.0 \
    redis>=5.0 \
    requests>=2.31 \
    pydantic>=2.0 \
    pydantic-settings>=2.0 \
    python-dotenv>=1.0 \
    python-arango>=8.0 \
    "psycopg[binary]>=3.1" \
    prometheus_client>=0.20

# Copy project root modules needed for predictive/prescriptive engines + channel registry
COPY agentic_tools/ /app/agentic_tools/
COPY data_utils/ /app/data_utils/
COPY main_configs.py /app/main_configs.py

# Copy shared + publisher
COPY services/__init__.py /app/services/__init__.py
COPY services/shared/ /app/services/shared/
COPY services/nba_publisher/ /app/services/nba_publisher/

ENV PYTHONPATH=/app

EXPOSE 8082

ENTRYPOINT ["python", "-m", "services.nba_publisher.publisher"]
