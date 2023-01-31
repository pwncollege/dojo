FROM python:3.7-slim-buster
WORKDIR /opt/CTFd
RUN mkdir -p /opt/CTFd /var/log/CTFd /var/uploads

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        libffi-dev \
        libssl-dev \
        git \
        openssh-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN adduser \
    --disabled-login \
    -u 1001 \
    --gecos "" \
    --shell /bin/bash \
    ctfd

COPY requirements.txt /opt/CTFd/
COPY CTFd/plugins/dojo_plugin/requirements.txt /opt/CTFd/CTFd/plugins/dojo_plugin/

RUN pip install -r requirements.txt --no-cache-dir
RUN pip install -r CTFd/plugins/dojo_plugin/requirements.txt --no-cache-dir

COPY . /opt/CTFd

RUN chmod +x /opt/CTFd/docker-entrypoint.sh \
    && chown -R 1001:1001 /opt/CTFd /var/log/CTFd /var/uploads

USER 1001
EXPOSE 8000
ENTRYPOINT ["/opt/CTFd/docker-entrypoint.sh"]