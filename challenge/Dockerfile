FROM ubuntu:24.04

RUN userdel -f -r ubuntu && \
    useradd -m hacker -s /bin/bash && \
    passwd -d hacker

USER hacker
WORKDIR /home/hacker
