# syntax=docker/dockerfile:1

FROM alpine:3.20.3

RUN apk add --no-cache \
    python3 \
    py3-pip \
    openssh-server-pam \
    openssh-client \
    docker-cli

RUN pip3 install --break-system-packages \
    requests \
    docker \
    redis \
    psycopg2-binary

RUN addgroup -g 995 docker && \
    adduser -S hacker -G docker -s /bin/sh && \
    mkdir -p /home/hacker/.docker && \
    echo '{ "detachKeys": "ctrl-q,ctrl-q" }' > /home/hacker/.docker/config.json

RUN mkdir -p /run/sshd

WORKDIR /opt/sshd
COPY . .
RUN chmod 700 /opt/sshd/auth.py

EXPOSE 22

COPY --chmod=755 <<EOF /docker-entrypoint.sh
#!/bin/sh
env > /etc/environment
if [ -f /var/mac/key ]; then
    mkdir -p /home/hacker/.ssh
    cp /var/mac/key /home/hacker/.ssh
    chmod 600 /home/hacker/.ssh/key
fi
exec /usr/sbin/sshd.pam -D -e -f /opt/sshd/sshd_config
EOF

ENTRYPOINT ["/docker-entrypoint.sh"]