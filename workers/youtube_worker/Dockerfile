FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY . /srv/youtube_worker
RUN mkdir -p /data/assets/videos
VOLUME ["/data"]
EXPOSE 8200
CMD ["uvicorn", "youtube_worker.app:app", "--host", "0.0.0.0", "--port", "8200"]
