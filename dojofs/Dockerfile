FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y \
        fuse \
        gcc \
        libfuse-dev \
        pkg-config && \
    rm -rf /var/lib/apt/lists/* && \
    pip install \
        docker \
        fusepy && \
    mkdir -p /run/fuse/dojofs

COPY ./dojofs.py /bin/dojofs

CMD ["/bin/dojofs", "/run/fuse/dojofs"]
