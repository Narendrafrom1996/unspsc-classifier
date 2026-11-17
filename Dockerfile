FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and database
COPY . .

# Ensure upload and download directories exist
RUN mkdir -p uploads downloads

EXPOSE 5000

ENV PORT=5000
ENV FLASK_DEBUG=0

CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 app:app
