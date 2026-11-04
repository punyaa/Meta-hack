FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY signalforge/ ./signalforge/
RUN pip install --no-cache-dir .

COPY templates/ ./templates/
COPY static/ ./static/
RUN mkdir -p data/runs

EXPOSE 8000
CMD ["sh", "-c", "uvicorn signalforge.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
