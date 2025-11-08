# syntax=docker/dockerfile:1

FROM ubuntu:24.04 AS kata-builder

ENV KATA_VERSION=3.19.1

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential bc flex bison libssl-dev libelf-dev dwarves \
      curl ca-certificates yq \
    && rm -rf /var/lib/apt/lists/*

ADD https://github.com/kata-containers/kata-containers.git#${KATA_VERSION} /src/kata-containers

WORKDIR /src/kata-containers/tools/packaging/kernel

RUN <<EOF
  KERNEL_VERSION=$(yq -r '.assets.kernel.version' ../../../versions.yaml)
  echo 'CONFIG_SECURITY_LANDLOCK=y' >> configs/fragments/x86_64/base.conf
  ./build-kernel.sh -v "$KERNEL_VERSION" setup
  ./build-kernel.sh -v "$KERNEL_VERSION" build
  ./build-kernel.sh -v "$KERNEL_VERSION" install
EOF

FROM ubuntu:24.04 AS dojo

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
        python3-requests
        unzip
        wget
        wireguard
EOF

RUN <<EOF
curl -fsSL https://get.docker.com | VERSION=27.5.1 sh
sed -i 's|-H fd:// ||' /lib/systemd/system/docker.service
EOF

COPY etc/docker/daemon*.json /tmp/
RUN cp /tmp/daemon.json /etc/docker/daemon.json

ADD https://raw.githubusercontent.com/moby/profiles/master/seccomp/default.json /etc/docker/seccomp.json

RUN <<EOF
KATA_VERSION=3.19.1
curl -L https://github.com/kata-containers/kata-containers/releases/download/${KATA_VERSION}/kata-static-${KATA_VERSION}-amd64.tar.xz | tar -xJ --strip-components=2 -C /opt
ln -s /opt/kata/bin/containerd-shim-kata-v2 /usr/local/bin/containerd-shim-kata-v2
EOF

COPY --from=kata-builder /usr/share/kata-containers/vmlinux.container /opt/kata/share/kata-containers/vmlinux.container

RUN <<EOF
cd /tmp
wget -O aws.zip "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip"
unzip aws.zip
./aws/install
rm -rf aws.zip aws
EOF

ADD https://github.com/CTFd/CTFd.git#3.6.0 /opt/CTFd
COPY ./ctfd/.coveragerc /opt/CTFd

COPY <<EOF /etc/fstab
shm /dev/shm tmpfs defaults,nosuid,nodev,noexec,size=50% 0 0
tmpfs /run/dojo tmpfs defaults,mode=755,shared 0 0
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

RUN find /opt/pwn.college/ctfd/patches -exec patch -d /opt/CTFd -p1 -N -i {} \;

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
EXPOSE 8001
CMD ["dojo", "init"]
