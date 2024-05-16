# NEW VM

```sh
hacker@(none):/$ sudo dd if=/dev/zero of=/data bs=1M count=4096
sudo: unable to resolve host (none): Name or service not known
4096+0 records in
4096+0 records out
4294967296 bytes (4.3 GB, 4.0 GiB) copied, 9.35822 s, 459 MB/s

hacker@(none):/$ time ipython -c 'import pwn'
real	0m1.971s
user	0m1.264s
sys	    0m0.288s
```

# OLD VM

```sh
hacker@vm_practice~program-misuse~level1:~$ sudo dd if=/dev/zero of=/data bs=1M count=4096
4096+0 records in
4096+0 records out
4294967296 bytes (4.3 GB, 4.0 GiB) copied, 52.2873 s, 82.1 MB/s

hacker@vm_practice~program-misuse~level1:~$ time ipython -c 'import pwn'
real    0m12.654s
user    0m2.138s
sys     0m1.990s
```

# MISC

CONFIG_FUSE_FS=m
CONFIG_CUSE=m
CONFIG_VIRTIO_FS=m

make -j$(nproc) modules
make modules_install

- What is our story for kernel challenges that require a custom kernel module, and the kernel version is changing?

root@practice~system-exploitation~level1-0:/opt/linux/linux-5.4# du -sh /usr/src/linux-headers-5.4.0-174
71M	/usr/src/linux-headers-5.4.0-174
root@practice~system-exploitation~level1-0:/opt/linux/linux-5.4# du -sh /usr/src/linux-headers-5.4.0-174-generic/
18M	/usr/src/linux-headers-5.4.0-174-generic/
root@practice~system-exploitation~level1-0:/opt/linux/linux-5.4# du -sh /boot/*
4.7M	/boot/System.map-5.4.0-174-generic
259K	/boot/config-5.4.0-174-generic
512	/boot/initrd.img
512	/boot/initrd.img.old
21M	/boot/test.img
512	/boot/vmlinuz
14M	/boot/vmlinuz-5.4.0-174-generic
512	/boot/vmlinuz.old
root@practice~system-exploitation~level1-0:/opt/linux/linux-5.4# du -sh /lib/modules/5.4.0-174-generic/
78M	/lib/modules/5.4.0-174-generic/

- Consider using the kvm config
root@practice~system-exploitation~level1-0:/opt/linux/linux-5.4# ls kernel/configs/kvm_guest.config
kernel/configs/kvm_guest.config

- How do we generate a vmlinux
- Does vmlinuz with linux-virtual contain debug symbols?





# KBFS

## Level 1
hacker@practice~kylebotfs~level-1:~$ ls -al /challenge/
total 420390
drwsr-xr-x  3 root root        10 Apr  1 17:19 .
drwxr-xr-x 18 root root        27 Apr  1 17:19 ..
-rwsr-xr-x  1 root root       143 Apr  1 00:52 .init
-rwsr-xr-x  1 root root         0 Mar 31 23:23 .kaslr
-rwsr-xr-x  1 root root         0 Mar 31 23:23 .panic_on_oops
-rwsr-xr-x  1 root root  12928000 Mar 31 06:20 bzImage
-rwsr-xr-x  1 root root    395840 Mar 31 23:31 challenge.ko
-rwsr-xr-x  1 root root     17560 Mar 31 23:42 mount_kbfs
drwsr-xr-x  3 root root         4 Apr  1 00:45 src
-rwsr-xr-x  1 root root 416671584 Mar 31 06:35 vmlinux
hacker@practice~kylebotfs~level-1:~$ cat /challenge/.init
#!/bin/bash

chmod 755 /challenge/src
chmod 755 /challenge/src/libkbfs
chmod 444 /challenge/src/kbfs.c
chmod 444 /challenge/src/libkbfs/kbfs.h

## Level 2
hacker@practice~kylebotfs~level-2:~$ ls -al /challenge/
total 395791
drwsr-xr-x  2 root root         8 Apr  1 17:19 .
drwxr-xr-x 18 root root        27 Apr  1 17:19 ..
-rwsr-xr-x  1 root root         0 Mar 31 23:23 .kaslr
-rwsr-xr-x  1 root root         0 Mar 31 23:23 .panic_on_oops
-rwsr-xr-x  1 root root  12928000 Mar 31 06:20 bzImage
-rwsr-xr-x  1 root root    395512 Mar 31 23:31 challenge.ko
-rwsr-xr-x  1 root root     17512 Mar 31 23:42 mount_kbfs
-rwsr-xr-x  1 root root 416671584 Mar 31 06:35 vmlinux

## Level 3
hacker@practice~kylebotfs~level-3:~$ ls -al /challenge/
total 420393
drwsr-xr-x  2 root root        10 Apr  1 17:20 .
drwxr-xr-x 18 root root        27 Apr  1 17:20 ..
-rwsr-xr-x  1 root root        45 Apr  1 00:49 .init
-rwsr-xr-x  1 root root        94 Mar 31 23:55 .initvm
-rwsr-xr-x  1 root root         0 Mar 31 23:23 .kaslr
-rwsr-xr-x  1 root root         0 Mar 31 23:23 .panic_on_oops
-rwsr-xr-x  1 root root  12928000 Mar 31 06:20 bzImage
-rwsr-xr-x  1 root root    393872 Mar 31 23:31 challenge.ko
-rwxr-xr-x  1 root root     17512 Mar 31 23:42 mount_kbfs
-rwsr-xr-x  1 root root 416671584 Mar 31 06:35 vmlinux
hacker@practice~kylebotfs~level-3:~$ cat /challenge/.init
#!/bin/bash

chmod 755 /challenge/mount_kbfs
hacker@practice~kylebotfs~level-3:~$ cat /challenge/.initvm
#!/bin/bash

chmod 755 /challenge/mount_kbfs
chmod 666 /dev/loop-control
chmod 666 /dev/loop*

## Level 4
hacker@practice~kylebotfs~level-4:~$ ls -al /challenge/
total 420392
drwsr-xr-x  2 root root        10 Apr  1 17:22 .
drwxr-xr-x 18 root root        27 Apr  1 17:22 ..
-rwsr-xr-x  1 root root        45 Apr  1 00:49 .init
-rwsr-xr-x  1 root root        94 Mar 31 23:55 .initvm
-rwsr-xr-x  1 root root         0 Mar 31 23:23 .kaslr
-rwsr-xr-x  1 root root         0 Mar 31 23:23 .panic_on_oops
-rwsr-xr-x  1 root root  12928000 Mar 31 06:20 bzImage
-rwsr-xr-x  1 root root    395856 Mar 31 23:31 challenge.ko
-rwxr-xr-x  1 root root     17512 Mar 31 23:42 mount_kbfs
-rwsr-xr-x  1 root root 416671584 Mar 31 06:35 vmlinux
hacker@practice~kylebotfs~level-4:~$ cat /challenge/.init
#!/bin/bash

chmod 755 /challenge/mount_kbfs
hacker@practice~kylebotfs~level-4:~$ cat /challenge/.initvm
#!/bin/bash

chmod 755 /challenge/mount_kbfs
chmod 666 /dev/loop-control
chmod 666 /dev/loop*

# OLD

cd /tmp
rm -r /tmp/fs
cp -r /opt/busybox/fs/ /tmp
cd /tmp/fs

rm linuxrc
mkdir -p bin etc dev dev/pts proc sys tmp home lib lib/modules newroot
cp -r /lib/modules/5.4.0-174-generic/ lib/modules/

cat << EOF > etc/fstab
proc /proc proc defaults 0 0
sys /sys sysfs defaults 0 0
tmp /tmp tmpfs defaults 0 0
devpts /dev/pts devpts defaults 0 0
EOF

cat << EOF > init
#!/bin/sh
echo Booting
set -e
mount -a

ip a

# modprobe 9pnet_virtio
# modprobe virtio_net
# modprobe virtiofs
mount -t virtiofs myfs /newroot

ip a

ls -al /newroot

# mount -t 9p -o trans=virtio,version=9p2000.L,nosuid /dev/root /newroot
# mount -t 9p -o trans=virtio,version=9p2000.L,nosuid /home/hacker /newroot/home/hacker

exec switch_root /newroot /init
EOF
chmod +x init

cat << EOF > /init
#!/bin/sh

set -e

mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t tmpfs tmp /tmp
mount -t devpts -o x-mount.mkdir devpts /dev/pts

ip link set dev lo up
ip addr add 10.0.2.15/24 dev eth0
ip route add 10.0.2.0/24 via 10.0.2.2 dev eth0 2>/dev/null || true  # Error: Nexthop has invalid gateway.
ip link set dev eth0 up

service ssh start

if [ -e /usr/sbin/docker-init ]; then
    exec /usr/sbin/docker-init /bin/sleep -- 6h
else
    exec /bin/sleep 6h
fi
EOF
chmod +x /init

find . | cpio -H newc -o | gzip > /boot/test.img
# BZIMAGE_PATH=/boot/vmlinuz vm start
# BZIMAGE_PATH=/tmp/kernel/bzImage0 vm start
vm start
vm logs
