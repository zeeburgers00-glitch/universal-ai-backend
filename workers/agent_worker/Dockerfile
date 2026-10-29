FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY . /srv/agent_worker
EXPOSE 8500
CMD ["uvicorn", "agent_worker.app:app", "--host", "0.0.0.0", "--port", "8500"]
