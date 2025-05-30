FROM alpine:3.20.3

RUN apk add --no-cache \
        python3 \
        py3-pip \
        openssh-server-pam \
        openssh-client \
        docker-cli \
        psycopg2

RUN pip3 install --break-system-packages requests==2.31.0 docker redis

RUN addgroup -g 995 docker && \
    adduser -S hacker -G docker -s /bin/sh && \
    mkdir -p /home/hacker/.docker && \
    echo '{ "detachKeys": "ctrl-q,ctrl-q" }' > /home/hacker/.docker/config.json

RUN mkdir -p /run/sshd

WORKDIR /opt/sshd
COPY . .
RUN chmod 700 /opt/sshd/auth.py

EXPOSE 22

ENTRYPOINT ["/usr/sbin/sshd.pam", "-D", "-e", "-f", "/opt/sshd/sshd_config"]
