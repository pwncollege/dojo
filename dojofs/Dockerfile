FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y \
        fuse && \
    rm -rf /var/lib/apt/lists/* && \
    pip install \
        docker \
        fusepy && \
    mkdir -p /run/dojofs/workspace

COPY ./dojofs /usr/local/bin/dojofs

CMD ["dojofs", "/run/dojofs/workspace"]
