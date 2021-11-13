#!/bin/sh

/usr/bin/qemu-system-x86_64 \
  -kernel "/opt/linux/bzImage" \
  -fsdev local,id=rootfs,path=/,security_model=passthrough \
  -device virtio-9p-pci,fsdev=rootfs,mount_tag=/dev/root \
  -fsdev local,id=homefs,path=/home/hacker,security_model=passthrough \
  -device virtio-9p-pci,fsdev=homefs,mount_tag=/home/hacker \
  -device e1000,mac=00:11:22:33:44:55,netdev=net0 \
  -netdev user,id=net0,hostfwd=tcp::22-:22 \
  -nographic \
  -monitor none \
  -append 'rw rootfstype=9p rootflags=trans=virtio console=ttyS0 init=/opt/pwn.college/kernel/init.sh'
