# GPU worker image; this is separate from the lightweight Vercel control plane.
# Pin and validate CUDA/PyTorch/model dependencies before production releases.
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY . /srv/voice_worker
RUN mkdir -p /data/assets /data/generated /data/profiles
VOLUME ["/data"]
EXPOSE 8100
CMD ["uvicorn", "voice_worker.app:app", "--host", "0.0.0.0", "--port", "8100"]
