FROM python:3.12-slim

# supercronic: Docker-native cron that logs to stdout and handles env vars
ENV SUPERCRONIC_VERSION=v0.2.33
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
         -o /usr/local/bin/supercronic && \
    chmod +x /usr/local/bin/supercronic && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir tiportfolio

WORKDIR /app

COPY strategies/ /app/strategies/
COPY crontab /etc/supercronic/crontab

CMD ["supercronic", "/etc/supercronic/crontab"]
