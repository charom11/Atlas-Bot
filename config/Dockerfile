FROM python:3.11-slim

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir rich websocket-client ccxt

# Copy codebase
COPY . .

# Expose web dashboard port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/api/status || exit 1

# Start both server and bot in 24/7 self-healing mode
CMD ["python", "main.py", "--trade-live", "--sizing-mode", "margin", "--margin-pct", "0.03", "--leverage", "50", "--threshold", "30", "--timeframe", "15m", "--max-positions", "5"]
