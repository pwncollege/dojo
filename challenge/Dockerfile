FROM ubuntu:20.04

RUN rm /etc/dpkg/dpkg.cfg.d/excludes

ENV DEBIAN_FRONTEND noninteractive
ENV LC_CTYPE=C.UTF-8

RUN dpkg --add-architecture i386
RUN apt-get update && \
    dpkg -l | grep ^ii | cut -d' ' -f3 | grep -v '^libgcc-s1:amd64$' | xargs apt-get install -y --reinstall && \
    apt-get install -y sudo \
                       build-essential \
                       git \
                       gcc-multilib \
                       g++-multilib \
                       clang \
                       llvm \
                       gdb \
                       gdb-multiarch \
                       qemu-system-x86 \
                       kmod \
                       openssh-server \
                       python-is-python3 \
                       python3-dev \
                       python3-pip \
                       ipython3 \
                       default-jdk \
                       net-tools \
                       iproute2 \
                       nasm \
                       cmake \
                       rubygems \
                       emacs \
                       vim \
                       nano \
                       ed \
                       zsh \
                       tmux \
                       screen \
                       binwalk \
                       strace \
                       ltrace \
                       autoconf \
                       socat \
                       netcat \
                       nmap \
                       curl \
                       wget \
                       tcpdump \
                       exiftool \
                       hexedit \
                       parallel \
                       patchelf \
                       genisoimage \
                       whiptail \
                       binutils \
                       bsdmainutils \
                       bsdutils \
                       debianutils \
                       diffutils \
                       elfutils \
                       findutils \
                       gnupg-utils \
                       keyutils \
                       pcaputils \
                       pcre2-utils \
                       psutils \
                       squashfs-tools \
                       unzip \
                       virtualenvwrapper \
                       upx-ucl \
                       man-db \
                       manpages-dev \
                       bison \
                       bc \
                       flex \
                       cpio \
                       libelf-dev \
                       libtool-bin \
                       libini-config-dev \
                       libssl-dev \
                       libffi-dev \
                       libglib2.0-dev \
                       libseccomp-dev \
                       libedit-dev \
                       libpixman-1-dev \
                       libc6:i386 \
                       libc6-dev-i386 \
                       libstdc++6:i386 \
                       libncurses5:i386

RUN yes | unminimize

RUN useradd -s /bin/bash -m hacker && \
    passwd -d hacker

RUN mkdir /opt/linux && wget -O - https://mirrors.edge.kernel.org/pub/linux/kernel/v5.x/linux-5.4.tar.gz | tar xzC /opt/linux
WORKDIR /opt/linux/linux-5.4
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
    echo 'CONFIG_PCI_HOST_GENERIC=y' >> .config && \
    echo "CONFIG_GDB_SCRIPTS=y" >> .config && \
    echo "CONFIG_DEBUG_INFO=y" >> .config && \
    echo "CONFIG_DEBUG_INFO_REDUCED=n" >> .config && \
    echo "CONFIG_DEBUG_INFO_SPLIT=n" >> .config && \
    echo "CONFIG_DEBUG_FS=y" >> .config && \
    echo "CONFIG_DEBUG_INFO_DWARF4=y" >> .config && \
    echo "CONFIG_DEBUG_INFO_BTF=y" >> .config && \
    echo "CONFIG_FRAME_POINTER=y" >> .config && \
    echo "CONFIG_DEVPTS_FS=y" >> .config
RUN make -j$(nproc) bzImage
RUN cp arch/x86/boot/bzImage ../bzImage && \
    ln -s $PWD/vmlinux ../vmlinux
WORKDIR /

RUN echo '    StrictHostKeyChecking no' >> /etc/ssh/ssh_config && \
    echo '    UserKnownHostsFile=/dev/null' >> /etc/ssh/ssh_config && \
    echo '    LogLevel ERROR' >> /etc/ssh/ssh_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/g' /etc/ssh/sshd_config && \
    sed -i 's/#PermitEmptyPasswords no/PermitEmptyPasswords yes/g' /etc/ssh/sshd_config && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/g' /etc/ssh/sshd_config

RUN curl -fsSL https://code-server.dev/install.sh | /bin/sh /dev/stdin --version 3.10.2
RUN mkdir -p /opt/code-server/extensions && code-server --extensions-dir=/opt/code-server/extensions --install-extension ms-python.python
RUN mv /usr/lib/code-server/lib/vscode/node_modules/vscode-ripgrep/bin/rg /usr/lib/code-server/lib/vscode/node_modules/vscode-ripgrep/bin/rg.orig && \
    echo '#!/usr/bin/python \n\
          \n\
          import sys \n\
          import os \n\
          \n\
          sys.argv[0] += ".orig" \n\
          sys.argv.remove("--follow") \n\
          os.execv(sys.argv[0], sys.argv)' \
    | awk '{$1=$1};1' > /usr/lib/code-server/lib/vscode/node_modules/vscode-ripgrep/bin/rg && \
    chmod +x /usr/lib/code-server/lib/vscode/node_modules/vscode-ripgrep/bin/rg

RUN git clone https://github.com/aquynh/capstone /opt/capstone && cd /opt/capstone && ./make.sh && ./make.sh install
RUN git clone --branch=5.1.0 --depth=1 https://github.com/radareorg/radare2 /opt/radare2 && cd /opt/radare2 && sys/install.sh
RUN git clone https://github.com/aflplusplus/aflplusplus /opt/aflplusplus && cd /opt/aflplusplus && make distrib && make install
RUN git clone https://github.com/yrp604/rappel /opt/rappel && cd /opt/rappel && make && cp bin/rappel /usr/bin/rappel
RUN wget https://github.com/0vercl0k/rp/releases/download/v2-beta/rp-lin-x64 -O /usr/bin/rp++ && chmod +x /usr/bin/rp++

RUN pip install git+git://github.com/Gallopsled/pwntools.git#egg=pwntools jupyter angr r2pipe asteval psutil

RUN git clone https://github.com/pwndbg/pwndbg /opt/pwndbg && cd /opt/pwndbg && ./setup.sh
RUN git clone https://github.com/hugsy/gef /opt/gef
RUN git clone https://github.com/jerdna-regeiz/splitmind /opt/splitmind

RUN git clone https://github.com/pwncollege/all-binutils /opt/all-binutils
RUN git clone https://github.com/pwncollege/babyauto-crackmes /opt/babyauto-crackmes

RUN ln -s /usr/bin/ipython3 /usr/bin/ipython

RUN mkdir /opt/pwn.college
COPY docker-entrypoint.sh /opt/pwn.college/docker-entrypoint.sh
COPY setuid_python.c /opt/pwn.college/setuid_python.c
COPY kernel /opt/pwn.college/kernel
COPY .tmux.conf /opt/pwn.college/.tmux.conf
COPY .gdbinit /opt/pwn.college/.gdbinit
COPY .radare2rc /opt/pwn.college/.radare2rc

RUN gcc /opt/pwn.college/setuid_python.c -o /opt/pwn.college/python && \
    rm /opt/pwn.college/setuid_python.c

RUN ln -s /opt/pwn.college/kernel/kernel /usr/local/bin/kernel

RUN ln -sf /home/hacker/.tmux.conf /root/.tmux.conf && \
    ln -sf /home/hacker/.gdbinit /root/.gdbinit && \
    ln -sf /home/hacker/.radare2rc /root/.radare2rc

RUN echo 'pwn.college{uninitialized}' > /flag && \
    chmod 400 /flag

RUN mkdir /challenge

RUN find / -type f -perm -4000 | xargs -r chmod u-s

RUN chmod u+s /opt/pwn.college/python /opt/pwn.college/kernel/kernel

WORKDIR /home/hacker
