FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y \
        fuse && \
    rm -rf /var/lib/apt/lists/* && \
    pip install \
        docker \
        fusepy && \
    mkdir -p /run/dojo/dojofs

COPY ./dojofs /usr/local/bin/dojofs

CMD ["dojofs", "/run/dojo/dojofs"]
