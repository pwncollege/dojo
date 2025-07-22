# syntax=docker/dockerfile:1

FROM ubuntu:24.04

SHELL ["/bin/bash", "-ceox", "pipefail"]

ENV DEBIAN_FRONTEND=noninteractive
ENV LC_CTYPE=C.UTF-8

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install -yqq <<EOF && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
        build-essential
        btrfs-progs
        curl
        git
        host
        htop
        iproute2
        iputils-ping
        jq
        kmod
        unzip
        wget
        wireguard
EOF

RUN <<EOF
curl -fsSL https://get.docker.com | /bin/sh
sed -i 's|-H fd:// ||' /lib/systemd/system/docker.service
EOF

COPY <<EOF /etc/docker/daemon.json
{
    "data-root": "/data/docker",
    "hosts": ["unix:///run/docker.sock"],
    "builder": {
        "Entitlements": {
            "security-insecure": true
        }
    }
}
EOF

ADD https://raw.githubusercontent.com/moby/profiles/master/seccomp/default.json /etc/docker/seccomp.json

RUN <<EOF
cd /tmp
wget -O aws.zip "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip"
unzip aws.zip
./aws/install
rm -rf aws.zip aws
EOF

ADD https://github.com/CTFd/CTFd.git#3.6.0 /opt/CTFd

COPY <<EOF /etc/fstab
tmpfs /run/dojofs tmpfs defaults,mode=755,shared 0 0
/data/homes /run/homefs none defaults,bind,nosuid 0 0
EOF

COPY <<EOF /etc/sysctl.d/90-dojo.conf
fs.inotify.max_user_instances = 8192
fs.inotify.max_user_watches = 1048576
kernel.pty.max = 1048576
kernel.core_pattern = core
kernel.apparmor_restrict_unprivileged_userns = 0
EOF

WORKDIR /opt/pwn.college
COPY . .

RUN <<EOF
find /opt/pwn.college/etc/systemd/system -type f -exec ln -s {} /etc/systemd/system/ \;
find /opt/pwn.college/etc/systemd/system -type f -name '*.timer' -exec sh -c \
    'ln -s "/etc/systemd/system/$(basename "{}")" "/etc/systemd/system/timers.target.wants/$(basename "{}")"' \;
ln -s /opt/pwn.college/etc/systemd/system/pwn.college.service /etc/systemd/system/multi-user.target.wants/
find /opt/pwn.college/dojo -type f -executable -exec ln -s {} /usr/local/bin/ \;
EOF

EXPOSE 22
EXPOSE 80
EXPOSE 443
CMD ["dojo", "init"]
