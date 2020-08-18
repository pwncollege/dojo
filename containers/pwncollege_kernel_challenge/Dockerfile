FROM pwncollege_challenge

RUN apt-get update && \
    apt-get install -y qemu-system-x86 \
                       bc \
                       flex \
                       libelf-dev \
                       cpio

RUN find / -type f -perm -4000 | xargs -r chmod u-s

WORKDIR /opt/pwn-college
RUN wget https://mirrors.edge.kernel.org/pub/linux/kernel/v4.x/linux-4.19.87.tar.gz
RUN tar xf linux-4.19.87.tar.gz
RUN rm linux-4.19.87.tar.gz

WORKDIR linux-4.19.87
RUN make defconfig
RUN echo 'CONFIG_NET_9P=y' >> .config && \
    echo 'CONFIG_NET_9P_DEBUG=n' >> .config && \
    echo 'CONFIG_9P_FS=y' >> .config && \
    echo 'CONFIG_9P_FS_POSIX_ACL=y' >> .config && \
    echo 'CONFIG_9P_FS_SECURITY=y' >> .config && \
    echo 'CONFIG_NET_9P_VIRTIO=y' >> .config && \
    echo 'CONFIG_VIRTIO_PCI=y' >> .config && \
    echo 'CONFIG_VIRTIO_BLK=y' >> .config && \
    echo 'CONFIG_VIRTIO_BLK_SCSI=y' >> .config && \
    echo 'CONFIG_VIRTIO_NET=y' >> .config && \
    echo 'CONFIG_VIRTIO_CONSOLE=y' >> .config && \
    echo 'CONFIG_HW_RANDOM_VIRTIO=y' >> .config && \
    echo 'CONFIG_DRM_VIRTIO_GPU=y' >> .config && \
    echo 'CONFIG_VIRTIO_PCI_LEGACY=y' >> .config && \
    echo 'CONFIG_VIRTIO_BALLOON=y' >> .config && \
    echo 'CONFIG_VIRTIO_INPUT=y' >> .config && \
    echo 'CONFIG_CRYPTO_DEV_VIRTIO=y' >> .config && \
    echo 'CONFIG_BALLOON_COMPACTION=y' >> .config && \
    echo 'CONFIG_PCI=y' >> .config && \
    echo 'CONFIG_PCI_HOST_GENERIC=y' >> .config
RUN make -j16 bzImage
RUN cp arch/x86/boot/bzImage /opt/pwn-college/bzImage

WORKDIR /opt/pwn-college
RUN wget https://busybox.net/downloads/busybox-1.31.1.tar.bz2
RUN tar xf busybox-1.31.1.tar.bz2
RUN rm busybox-1.31.1.tar.bz2

WORKDIR busybox-1.31.1
RUN make defconfig
RUN sed -i 's/# CONFIG_STATIC is not set/CONFIG_STATIC=y/g' .config
RUN make -j16
RUN make install

WORKDIR /opt/pwn-college
RUN mkdir fs

WORKDIR fs
RUN mkdir -p bin sbin etc proc sys usr/bin usr/sbin root home/ctf
RUN echo 'root:x:0:0:root:/root:/bin/sh' >> etc/passwd && \
    echo 'ctf:x:1000:1000:ctf:/home/ctf:/bin/sh' >> etc/passwd

WORKDIR /opt/pwn-college
RUN cp -a busybox-1.31.1/_install/* fs

COPY init fs

COPY launch.sh .

COPY launch.c .
RUN gcc launch.c -o /launch
RUN chmod u+s /launch

WORKDIR /