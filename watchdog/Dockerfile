FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y \
        cron && \
    rm -rf /var/lib/apt/lists/* && \
    pip install \
        docker

COPY docker_cleanup.py /usr/local/bin/docker_cleanup.py

COPY <<'EOF' /etc/cron.d/cleanup-cron
0 9 * * * /usr/local/bin/docker_cleanup.py >> /dev/stdout 2>&1
EOF

RUN crontab /etc/cron.d/cleanup-cron

CMD ["cron", "-f"]
