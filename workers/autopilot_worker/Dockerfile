FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
COPY workers/autopilot_worker/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY workers/autopilot_worker/ /srv/autopilot_worker/
COPY catalog/youtube_agent_fleet.json /srv/catalog/youtube_agent_fleet.json
CMD ["celery","-A","autopilot_worker.app.celery_app","worker","--loglevel=INFO","--concurrency=5"]
