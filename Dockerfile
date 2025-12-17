FROM python:3.10-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scripts directory
COPY scripts/ ./scripts/

# Run unbuffered to see logs in Docker
ENV PYTHONUNBUFFERED=1

# Default command - can be overridden when running
# Example: docker-compose run ingestor python scripts/fetch_observations.py -n 50
CMD ["bash"]
