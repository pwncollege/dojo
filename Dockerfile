FROM ubuntu:22.04

ENV DEBIAN_FRONTEND noninteractive
ENV LC_CTYPE=C.UTF-8

RUN apt-get update && \
    apt-get install -y \
        awscli \
        build-essential \
        curl \
        git \
        host \
        htop \
        iproute2 \
        iputils-ping \
        jq \
        unzip \
        wget \
        zfsutils-linux

RUN curl -fsSL https://get.docker.com | /bin/sh
RUN echo '{ "data-root": "/opt/pwn.college/data/docker", "builder": {"Entitlements": {"security-insecure": true}} }' > /etc/docker/daemon.json
RUN wget -O /etc/docker/seccomp.json https://raw.githubusercontent.com/moby/moby/master/profiles/seccomp/default.json

RUN git clone --branch 3.6.0 https://github.com/CTFd/CTFd /opt/CTFd

RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.service /etc/systemd/system/pwn.college.service
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.logging.service /etc/systemd/system/pwn.college.logging.service
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.backup.service /etc/systemd/system/pwn.college.backup.service
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.backup.timer /etc/systemd/system/pwn.college.backup.timer
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.cachewarmer.service /etc/systemd/system/pwn.college.cachewarmer.service
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.cachewarmer.timer /etc/systemd/system/pwn.college.cachewarmer.timer
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.cloud.backup.service /etc/systemd/system/pwn.college.cloud.backup.service
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.cloud.backup.timer /etc/systemd/system/pwn.college.cloud.backup.timer
RUN ln -s /etc/systemd/system/pwn.college.service /etc/systemd/system/multi-user.target.wants/pwn.college.service
RUN ln -s /etc/systemd/system/pwn.college.logging.service /etc/systemd/system/multi-user.target.wants/pwn.college.logging.service
RUN ln -s /etc/systemd/system/pwn.college.backup.timer /etc/systemd/system/timers.target.wants/pwn.college.backup.timer
RUN ln -s /etc/systemd/system/pwn.college.cachewarmer.timer /etc/systemd/system/timers.target.wants/pwn.college.cachewarmer.timer
RUN ln -s /etc/systemd/system/pwn.college.cloud.backup.timer /etc/systemd/system/timers.target.wants/pwn.college.cloud.backup.timer

RUN mkdir -p /opt/pwn.college
ADD . /opt/pwn.college
RUN find /opt/pwn.college/dojo -type f -exec ln -s {} /usr/bin/ \;

EXPOSE 22
EXPOSE 80
EXPOSE 443
WORKDIR /opt/pwn.college
CMD ["dojo", "start"]
