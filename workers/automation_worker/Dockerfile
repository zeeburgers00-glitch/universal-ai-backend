FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY . /srv/automation_worker
EXPOSE 8600
CMD ["uvicorn", "automation_worker.app:app", "--host", "0.0.0.0", "--port", "8600"]
