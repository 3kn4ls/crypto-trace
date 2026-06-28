FROM python:3.11-slim

WORKDIR /app

# Install system fonts for PDF export (DejaVu supports Spanish characters).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# SQLite database lives on a mounted volume so data survives container restarts.
ENV CRYPTO_TRACE_DB=/data/crypto_trace.db
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
