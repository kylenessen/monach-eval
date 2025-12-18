FROM python:3.10-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scripts directory and entrypoint
COPY scripts/ ./scripts/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Run unbuffered to see logs in Docker
ENV PYTHONUNBUFFERED=1

# Entrypoint initializes database then keeps container running
ENTRYPOINT ["./entrypoint.sh"]
