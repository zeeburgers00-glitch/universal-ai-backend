FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    procps \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && npm install --global rea-agents@6.8.0 \
    && rm -rf /var/lib/apt/lists/* /root/.npm

WORKDIR /srv

COPY requirements.txt /srv/rea_worker/requirements.txt
RUN pip install --no-cache-dir -r /srv/rea_worker/requirements.txt

COPY . /srv/rea_worker

RUN useradd --create-home --shell /usr/sbin/nologin reauser \
    && mkdir -p /workspace/targets \
    && chown -R reauser:reauser /workspace /srv

USER reauser
ENV PYTHONPATH=/srv \
    REA_ALLOWED_WORKSPACE_ROOT=/workspace/targets

EXPOSE 8700
CMD ["uvicorn", "rea_worker.app:app", "--host", "0.0.0.0", "--port", "8700"]
