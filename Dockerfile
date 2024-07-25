FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LC_CTYPE=C.UTF-8

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        curl \
        git \
        host \
        htop \
        iproute2 \
        iputils-ping \
        jq \
        unzip \
        wget

RUN curl -fsSL https://get.docker.com | /bin/sh
RUN echo '{ "data-root": "/data/docker", "builder": {"Entitlements": {"security-insecure": true}} }' > /etc/docker/daemon.json
RUN wget -O /etc/docker/seccomp.json https://raw.githubusercontent.com/moby/moby/master/profiles/seccomp/default.json

RUN cd /tmp && \
    wget -O awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf awscliv2.zip aws

RUN git clone --branch 3.6.0 https://github.com/CTFd/CTFd /opt/CTFd

RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.service /etc/systemd/system/pwn.college.service && \
    ln -s /opt/pwn.college/etc/systemd/system/pwn.college.backup.service /etc/systemd/system/pwn.college.backup.service && \
    ln -s /opt/pwn.college/etc/systemd/system/pwn.college.backup.timer /etc/systemd/system/pwn.college.backup.timer && \
    ln -s /opt/pwn.college/etc/systemd/system/pwn.college.cachewarmer.service /etc/systemd/system/pwn.college.cachewarmer.service && \
    ln -s /opt/pwn.college/etc/systemd/system/pwn.college.cachewarmer.timer /etc/systemd/system/pwn.college.cachewarmer.timer && \
    ln -s /opt/pwn.college/etc/systemd/system/pwn.college.cloud.backup.service /etc/systemd/system/pwn.college.cloud.backup.service && \
    ln -s /opt/pwn.college/etc/systemd/system/pwn.college.cloud.backup.timer /etc/systemd/system/pwn.college.cloud.backup.timer && \
    ln -s /etc/systemd/system/pwn.college.service /etc/systemd/system/multi-user.target.wants/pwn.college.service && \
    ln -s /etc/systemd/system/pwn.college.backup.timer /etc/systemd/system/timers.target.wants/pwn.college.backup.timer && \
    ln -s /etc/systemd/system/pwn.college.cachewarmer.timer /etc/systemd/system/timers.target.wants/pwn.college.cachewarmer.timer && \
    ln -s /etc/systemd/system/pwn.college.cloud.backup.timer /etc/systemd/system/timers.target.wants/pwn.college.cloud.backup.timer

WORKDIR /opt/pwn.college
COPY . .

RUN find /opt/pwn.college/dojo -type f -exec ln -s {} /usr/bin/ \;

EXPOSE 22
EXPOSE 80
EXPOSE 443
CMD ["dojo", "init"]
