FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY . /srv/autopilot_worker
CMD ["celery","-A","autopilot_worker.app.celery_app","worker","--loglevel=INFO","--concurrency=5"]
