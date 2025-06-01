FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y \
        cron && \
    rm -rf /var/lib/apt/lists/* && \
    pip install \
        docker

COPY docker_remove_containers.py /usr/local/bin/docker_remove_containers
COPY docker_prune_images.py /usr/local/bin/docker_prune_images

COPY <<'EOF' /etc/cron.d/watchdog-cron
*/5 * * * * /usr/local/bin/docker_remove_containers >> /proc/1/fd/1 2>> /proc/1/fd/2
0 9 * * * /usr/local/bin/docker_prune_images >> /proc/1/fd/1 2>> /proc/1/fd/2
EOF

RUN crontab /etc/cron.d/watchdog-cron

CMD ["cron", "-f"]
