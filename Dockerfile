FROM python:3.10-slim

WORKDIR /app

# Install system dependencies if needed (none for now)

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy script
COPY scripts/ingest_data.py .

# Run unbuffered to see logs in Docker
ENV PYTHONUNBUFFERED=1

CMD ["python", "ingest_data.py"]
