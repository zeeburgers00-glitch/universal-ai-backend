FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY . /srv/media_worker
RUN mkdir -p /data/assets/videos /data/assets/audio /data/assets/images /data/assets/subtitles /data/assets/other /data/workflows
VOLUME ["/data"]
EXPOSE 8400
CMD ["uvicorn", "media_worker.app:app", "--host", "0.0.0.0", "--port", "8400"]
