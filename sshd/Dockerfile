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

RUN adduser -D hacker && \
    addgroup -g 995 docker && \
    addgroup hacker docker && \
    mkdir -p /home/hacker/.docker /home/hacker/.ssh && \
    chown -R hacker:hacker /home/hacker

RUN mkdir -p /run/sshd

WORKDIR /opt/sshd
COPY . .
RUN chmod 700 /opt/sshd/auth.py

EXPOSE 22

COPY --chmod=755 <<EOF /docker-entrypoint.sh
#!/bin/sh
env > /etc/environment
if command -v docker >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    for i in 1 2 3 4 5 6 7 8 9 10; do
        python3 -c "
import json, subprocess, sys
try:
    sshd = json.loads(subprocess.check_output(['docker', 'inspect', 'sshd'], timeout=5))
    sshd_nets = set(sshd[0]['NetworkSettings']['Networks'].keys())
    for name, port in [('ctfd', 8000), ('nginx', 80)]:
        ctfd = json.loads(subprocess.check_output(['docker', 'inspect', name], timeout=5))
        ctfd_nets = ctfd[0]['NetworkSettings']['Networks']
        for net in sshd_nets:
            if net in ctfd_nets and ctfd_nets[net].get('IPAddress'):
                print('http://' + ctfd_nets[net]['IPAddress'] + ':' + str(port) + '/pwncollege_api/v1')
                sys.exit(0)
except Exception:
    sys.exit(1)
" > /run/dojo_ctfd_url 2>/dev/null && [ -s /run/dojo_ctfd_url ] && break
        sleep 1
    done
fi
if [ -f /var/mac/key ]; then
    cp /var/mac/key /home/hacker/.ssh
    chown hacker:hacker /home/hacker/.ssh/key
    chmod 600 /home/hacker/.ssh/key
fi
exec /usr/sbin/sshd.pam -D -e -f /opt/sshd/sshd_config
EOF

ENTRYPOINT ["/docker-entrypoint.sh"]
