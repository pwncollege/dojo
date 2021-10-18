#!/bin/sh

if [ ! -f "/opt/pwn.college/data/config.env" ] && [ -z "$SETUP_HOSTNAME" ]; then
    echo "Error: instance not setup; rerun with SETUP_HOSTNAME environment variable!"
    exit 1
fi

if [ ! -f /opt/pwn.college/data/config.env ]; then
    cat <<EOF >> /opt/pwn.college/data/config.env
SECRET_KEY=$(openssl rand -hex 16)
DOCKER_PSLR=$(openssl rand -hex 16)
HOST_DATA_PATH=/opt/pwn.college/data
VIRTUAL_HOST=$SETUP_HOSTNAME
VIRTUAL_PORT=8000
LETSENCRYPT_HOST=$SETUP_HOSTNAME
EOF
fi

if [ ! -f /opt/pwn.college/data/homes/homefs ]; then
    mkdir -p /opt/pwn.college/data/homes
    mkdir -p /opt/pwn.college/data/homes/data
    mkdir -p /opt/pwn.college/data/homes/nosuid
    dd if=/dev/zero of=/opt/pwn.college/data/homes/homefs bs=1M count=0 seek=1000
    mkfs.ext4 -O ^has_journal /opt/pwn.college/data/homes/homefs
    mount /opt/pwn.college/data/homes/homefs -o X-mount.mkdir /opt/pwn.college/data/homes/homefs_mount
    rm -rf /opt/pwn.college/data/homes/homefs_mount/lost+found/
    cp -a /etc/skel/. /opt/pwn.college/data/homes/homefs_mount
    chown -R hacker:hacker /opt/pwn.college/data/homes/homefs_mount
    umount /opt/pwn.college/data/homes/homefs_mount
    rm -rf /opt/pwn.college/data/homes/homefs_mount
fi

for i in $(seq 1 1024); do
    if [ -e /dev/loop$i ]; then
        continue
    fi
    mknod /dev/loop$i b 7 $i
    chown --reference=/dev/loop0 /dev/loop$i
    chmod --reference=/dev/loop0 /dev/loop$i
done

mkdir -p /opt/pwn.college/data/logging

sysctl -w kernel.pty.max=1048576
echo core > /proc/sys/kernel/core_pattern

exec /usr/bin/systemd
