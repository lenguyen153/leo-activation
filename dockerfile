# 1. Use the specific image we know works
FROM apache/age:latest

# 2. Switch to root to install extensions
USER root

# 3. Install dependencies
# We install 'postgresql-server-dev-all' which includes a helper to find the right version,
# OR we explicitly install the version matching the image.
# Since 'apache/age:latest' is likely PG16, we explicitly target 16.
# We also update the PATH to ensure pg_config is found.
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    postgresql-server-dev-17 \
    && rm -rf /var/lib/apt/lists/*

# 4. Clone and install pgvector
# We explicitly set PG_CONFIG to ensure the makefile uses the correct headers
RUN cd /tmp \
    && git clone --branch v0.7.0 https://github.com/pgvector/pgvector.git \
    && cd pgvector \
    && make PG_CONFIG=/usr/lib/postgresql/16/bin/pg_config \
    && make install

# 5. Clean up
RUN rm -rf /tmp/pgvector

# 6. Switch back to postgres user
USER postgres