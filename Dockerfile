FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
COPY scripts /app/scripts
COPY .env.example /app/.env.example

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data/raw /app/data/parsed/reports /app/data/parsed/banks /app/data/manifests

ENV PYTHONPATH=/app
