# OMNIX — Multi-stage Docker build
# Usage:
#   docker build -t omnix .
#   docker run -p 8765:8765 -p 8766:8766 omnix

# ── Stage 1: Dependencies ──
FROM python:3.11-slim AS deps

WORKDIR /app

# Install system deps for numpy/opencv (optional but common)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1-mesa-glx \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Application ──
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install minimal runtime libs
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1-mesa-glx \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Create non-root user
RUN groupadd -r omnix && useradd -r -g omnix -m -s /bin/bash omnix

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY sdk/ ./sdk/
COPY scripts/ ./scripts/
COPY Makefile pyproject.toml requirements.txt ./

# Create data directory for SQLite persistence
RUN mkdir -p /app/data && chown omnix:omnix /app/data

# Set environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMNIX_HOST=0.0.0.0 \
    OMNIX_PORT=8765 \
    OMNIX_WS_PORT=8766 \
    OMNIX_DB_BACKEND=sqlite \
    OMNIX_DB_PATH=/app/data/omnix.db \
    OMNIX_LOG_JSON=true \
    OMNIX_ENV=production

# Switch to non-root user
USER omnix

# Expose ports: HTTP + WebSocket
EXPOSE 8765 8766

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8765/healthz || exit 1

# Start server
CMD ["python", "backend/server_simple.py"]
