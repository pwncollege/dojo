FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libfuse3-dev \
        pkg-config && \
    rm -rf /var/lib/apt/lists/* && \
    pip install \
        docker \
        pyfuse3 && \
    mkdir -p /run/dojo/dojofs

COPY ./dojofs /usr/local/bin/dojofs

CMD ["dojofs", "/run/dojo/dojofs"]
