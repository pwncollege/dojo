#!/bin/bash

cd /opt/pwn-college

umask 377

cp /flag fs
cp /*.ko fs

pushd fs
find . -print0 | cpio --null -ov --format=newc | gzip -9 > /opt/pwn-college/initramfs.cpio.gz
popd

if id ctf | grep -q sudo; then
    /usr/bin/qemu-system-x86_64 \
        -kernel /opt/pwn-college/bzImage \
        -initrd /opt/pwn-college/initramfs.cpio.gz \
        -fsdev local,security_model=passthrough,id=fsdev0,path=/home/ctf \
        -device virtio-9p-pci,id=fs0,fsdev=fsdev0,mount_tag=hostshare \
        -nographic \
        -monitor none \
        -s \
        -append "console=ttyS0"
else
    /usr/bin/qemu-system-x86_64 \
        -kernel /opt/pwn-college/bzImage \
        -initrd /opt/pwn-college/initramfs.cpio.gz \
        -fsdev local,security_model=passthrough,id=fsdev0,path=/home/ctf \
        -device virtio-9p-pci,id=fs0,fsdev=fsdev0,mount_tag=hostshare \
        -nographic \
        -monitor none \
        -append "console=ttyS0"
fi
