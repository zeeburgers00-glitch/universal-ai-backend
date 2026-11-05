FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "httpx>=0.27,<1.0"
COPY worker.py /srv/worker.py
CMD ["python", "/srv/worker.py"]
