FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY . /srv/channel_worker
EXPOSE 8300
CMD ["uvicorn", "channel_worker.app:app", "--host", "0.0.0.0", "--port", "8300"]
