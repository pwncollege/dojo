FROM ubuntu:20.04

ENV DEBIAN_FRONTEND noninteractive
ENV LC_CTYPE=C.UTF-8

RUN apt-get update && \
    apt-get install -y build-essential \
                       git \
                       curl \
                       wget \
                       python-is-python3 \
                       python3-dev \
                       python3-pip \
                       openssh-server

RUN curl -fsSL https://get.docker.com | /bin/sh

RUN pip install docker docker-compose

RUN useradd -m hacker
RUN usermod -aG docker hacker
RUN mkdir -p /home/hacker/.docker
RUN echo '{ "detachKeys": "ctrl-q,ctrl-q" }' > /home/hacker/.docker/config.json

RUN mkdir -p /opt/pwn.college
ADD docker-entrypoint.sh /opt/pwn.college/docker-entrypoint.sh
ADD script /opt/pwn.college/script
ADD ssh /opt/pwn.college/ssh
ADD logging /opt/pwn.college/logging
ADD nginx-proxy /opt/pwn.college/nginx-proxy
ADD challenge /opt/pwn.college/challenge
ADD CTFd /opt/pwn.college/CTFd
ADD dojo_plugin /opt/pwn.college/CTFd/CTFd/plugins/dojo_plugin
ADD dojo_theme /opt/pwn.college/CTFd/CTFd/themes/dojo_theme
ADD docker-compose.yml /opt/pwn.college/docker-compose.yml

ADD etc/ssh/sshd_config /etc/ssh/sshd_config
ADD etc/systemd/system/pwn.college.service /etc/systemd/system/pwn.college.service
ADD etc/systemd/system/pwn.college.logging.service /etc/systemd/system/pwn.college.logging.service

RUN find /opt/pwn.college/script -type f -exec ln -s {} /usr/bin/ \;

RUN ln -s /etc/systemd/system/pwn.college.service /etc/systemd/system/multi-user.target.wants/pwn.college.service
RUN ln -s /etc/systemd/system/pwn.college.logging.service /etc/systemd/system/multi-user.target.wants/pwn.college.logging.service

WORKDIR /opt/pwn.college
ENTRYPOINT ["/opt/pwn.college/docker-entrypoint.sh"]
