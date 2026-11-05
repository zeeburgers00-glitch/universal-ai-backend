FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg powers the command layer's long-video renderer; DejaVu gives captions a font.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# The default local SQLite state path must be writable by the non-root API user.
RUN mkdir -p /app/data && chown app:app /app/data

USER app

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
