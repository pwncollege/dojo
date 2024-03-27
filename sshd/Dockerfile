FROM alpine:latest

RUN apk add --no-cache \
        python3 \
        py3-pip \
        openssh-server-pam \
	docker-cli \
	mysql-client

RUN pip3 install --break-system-packages docker

RUN delgroup ping && \
    addgroup -g 999 docker && \
    adduser -S hacker -G docker -s /bin/sh && \
    mkdir -p /home/hacker/.docker && \
    echo '{ "detachKeys": "ctrl-q,ctrl-q" }' > /home/hacker/.docker/config.json

RUN mkdir -p /run/sshd

WORKDIR /opt/sshd
COPY . .
RUN chmod 700 /opt/sshd/auth.py

EXPOSE 22

ENTRYPOINT ["/opt/sshd/start.sh"]
