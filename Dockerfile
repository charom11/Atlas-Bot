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

# The trading bot does not expose a verified HTTP dashboard on 8080.
# Use a process-level health check so Docker does not report a false unhealthy state.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD pgrep -f "python main.py" >/dev/null || exit 1

# Start the trading bot
CMD ["python", "main.py", "--trade-live", "--sizing-mode", "margin", "--margin-pct", "0.03", "--leverage", "50", "--threshold", "30", "--timeframe", "15m", "--max-positions", "5"]
