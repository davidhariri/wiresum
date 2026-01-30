FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Copy application code
COPY wiresum/ wiresum/

# Install the package
RUN pip install --no-cache-dir -e .

# Create data directory for SQLite
RUN mkdir -p /data

# Set default environment variables
ENV WIRESUM_DB_PATH=/data/wiresum.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "wiresum.server:app", "--host", "0.0.0.0", "--port", "8000"]
