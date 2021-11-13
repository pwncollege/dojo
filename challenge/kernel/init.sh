#!/bin/sh

set -e

mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devpts -o x-mount.mkdir devpts /dev/pts
mount -t 9p -o trans=virtio,version=9p2000.L,nosuid /home/hacker /home/hacker

python -c "import socket; socket.sethostname('kernel_$(cat /etc/hostname)')"

ip link set dev lo up
ip addr add 10.0.2.15/24 dev eth0
ip route add 10.0.2.0/24 via 10.0.2.2 dev eth0 2>/dev/null || true  # ignore: Error: Nexthop has invalid gateway.
ip link set dev eth0 up

service ssh start

exec /usr/sbin/docker-init /usr/bin/dmesg -- --follow
