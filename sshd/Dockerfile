FROM alpine:latest

RUN apk add --no-cache \
        build-base \
        python3 \
        python3-dev \
        py3-pip \
        mariadb-dev \
        openssh-server-pam \
        kubectl

RUN pip3 install --break-system-packages \
    kubernetes \
    mysqlclient \
    pyyaml

RUN adduser -S hacker -s /bin/sh && \
    mkdir -p /run/sshd

WORKDIR /opt/sshd
COPY . .
RUN chmod 700 /opt/sshd/auth.py

EXPOSE 22

ENTRYPOINT ["/usr/sbin/sshd.pam", "-D", "-e", "-f", "/opt/sshd/sshd_config"]
