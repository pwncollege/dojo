#!/bin/sh

# adamd: hack here so that the auth.py command can get the environment variables we set in the docker compose
printenv | grep -v "no_proxy" >> /etc/environment

/usr/sbin/sshd.pam -D -e -f /opt/sshd/sshd_config
