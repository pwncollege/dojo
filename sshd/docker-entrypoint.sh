#!/bin/sh
set -e

env > /etc/environment
if [ -f /var/mac/key ]; then
    cp /var/mac/key /home/hacker/.ssh
    chown hacker:hacker /home/hacker/.ssh/key
    chmod 600 /home/hacker/.ssh/key
fi

if [ "$SSH_PIPER_ENABLED" = "true" ]; then
    /usr/sbin/sshd.pam -D -e -f /opt/sshd/sshd_config_upstream &
    exec /usr/local/bin/sshpiperd \
        --port 22 \
        -i /etc/ssh/ssh_host_ed25519_key \
        --server-key-generate-mode notexist \
        /usr/local/bin/dojo-sshpiper-plugin \
        --endpoint "${SSH_PIPER_PROVISION_ENDPOINT}" \
        --token "${SSH_PIPER_API_TOKEN}" \
        --upstream-host "${SSH_PIPER_UPSTREAM_HOST:-127.0.0.1}" \
        --upstream-port "${SSH_PIPER_UPSTREAM_PORT:-2222}" \
        --upstream-user "${SSH_PIPER_UPSTREAM_USER:-hacker}"
fi

exec /usr/sbin/sshd.pam -D -e -f /opt/sshd/sshd_config
