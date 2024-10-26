FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y \
        btrfs-progs && \
    rm -rf /var/lib/apt/lists/* && \
    pip install \
        flask \
        gunicorn \
        requests

WORKDIR /opt/homefs
COPY . .

EXPOSE 80
CMD ["gunicorn", \
     "homefs:create_app()", \
     "--bind=unix:/run/docker/plugins/homefs.sock", \
     "--bind=0.0.0.0:80", \
     "--workers=8", \
     "--access-logfile=-"]
