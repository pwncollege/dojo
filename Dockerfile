FROM ubuntu:22.04

ENV DEBIAN_FRONTEND noninteractive
ENV LC_CTYPE=C.UTF-8

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        git \
        curl \
        wget \
        jq \
        iproute2 \
        iputils-ping \
        host \
        htop

RUN curl -fsSL https://get.docker.com | /bin/sh
RUN echo '{ "data-root": "/opt/pwn.college/data/docker" }' > /etc/docker/daemon.json

# TODO: this can be removed with docker-v22 (buildx will be default)
RUN docker buildx install

RUN git clone --branch 3.6.0 https://github.com/CTFd/CTFd /opt/CTFd

RUN wget -O /etc/docker/seccomp.json https://raw.githubusercontent.com/moby/moby/master/profiles/seccomp/default.json

RUN mkdir -p /opt/pwn.college
ADD . /opt/pwn.college

RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.service /etc/systemd/system/pwn.college.service
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.logging.service /etc/systemd/system/pwn.college.logging.service
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.backup.service /etc/systemd/system/pwn.college.backup.service
RUN ln -s /opt/pwn.college/etc/systemd/system/pwn.college.backup.timer /etc/systemd/system/pwn.college.backup.timer
RUN ln -s /etc/systemd/system/pwn.college.service /etc/systemd/system/multi-user.target.wants/pwn.college.service
RUN ln -s /etc/systemd/system/pwn.college.logging.service /etc/systemd/system/multi-user.target.wants/pwn.college.logging.service
RUN ln -s /etc/systemd/system/pwn.college.backup.timer /etc/systemd/system/timers.target.wants/pwn.college.backup.timer

RUN find /opt/pwn.college/script -type f -exec ln -s {} /usr/bin/ \;

EXPOSE 22
EXPOSE 80
EXPOSE 443

WORKDIR /opt/pwn.college
CMD ["dojo", "start"]
