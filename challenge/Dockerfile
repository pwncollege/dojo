# syntax=docker/dockerfile:1

ARG UBUNTU_VERSION=20.04
ARG DOJO_CHALLENGE=challenge-mini
ARG INSTALL_IDA=False

FROM ubuntu:${UBUNTU_VERSION} as essentials

SHELL ["/bin/bash", "-ceov", "pipefail"]

ENV DEBIAN_FRONTEND noninteractive
ENV LC_CTYPE=C.UTF-8

RUN <<EOF
    rm -f /etc/apt/apt.conf.d/docker-clean
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

    (set +o pipefail; yes | unminimize)

    dpkg --add-architecture i386
EOF

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install -yqq <<EOF
        curl
        socat
        sudo
        vim
        wget
        unzip
EOF

RUN rm -f /usr/lib/python3.*/EXTERNALLY-MANAGED

################################################################################

FROM essentials as builder-essentials

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install -yqq <<EOF
        build-essential
EOF

################################################################################

FROM builder-essentials as builder

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install -yqq <<EOF
        autoconf
        bc
        bison
        clang
        cmake
        cpio
        openjdk-17-jdk
        flex
        g++-multilib
        gcc-multilib
        git
        libc6-dev-i386
        libc6:i386
        libedit-dev
        libelf-dev
        libffi-dev
        libglib2.0-dev
        libgmp-dev
        libini-config-dev
        libncurses5:i386
        libpcap-dev
        libpixman-1-dev
        libseccomp-dev
        libssl-dev
        libstdc++6:i386
        libtool-bin
        llvm
        man-db
        manpages-dev
        nasm
        python-is-python3
        python3-dev
        python3-pip
        rubygems
        squashfs-tools
        upx-ucl
EOF

################################################################################

FROM builder as builder-kernel

RUN <<EOF
    mkdir /opt/linux
    wget -O - https://mirrors.edge.kernel.org/pub/linux/kernel/v5.x/linux-5.4.tar.gz | tar xzC /opt/linux
    cd /opt/linux/linux-5.4
    make defconfig
EOF

RUN awk '{$1=$1};1' >> /opt/linux/linux-5.4/.config <<EOF
    CONFIG_9P_FS=y
    CONFIG_9P_FS_POSIX_ACL=y
    CONFIG_9P_FS_SECURITY=y
    CONFIG_BALLOON_COMPACTION=y
    CONFIG_CRYPTO_DEV_VIRTIO=y
    CONFIG_DEBUG_FS=y
    CONFIG_DEBUG_INFO=y
    CONFIG_DEBUG_INFO_BTF=y
    CONFIG_DEBUG_INFO_DWARF4=y
    CONFIG_DEBUG_INFO_REDUCED=n
    CONFIG_DEBUG_INFO_SPLIT=n
    CONFIG_DEVPTS_FS=y
    CONFIG_DRM_VIRTIO_GPU=y
    CONFIG_FRAME_POINTER=y
    CONFIG_GDB_SCRIPTS=y
    CONFIG_HW_RANDOM_VIRTIO=y
    CONFIG_HYPERVISOR_GUEST=y
    CONFIG_NET_9P=y
    CONFIG_NET_9P_DEBUG=n
    CONFIG_NET_9P_VIRTIO=y
    CONFIG_PARAVIRT=y
    CONFIG_PCI=y
    CONFIG_PCI_HOST_GENERIC=y
    CONFIG_VIRTIO_BALLOON=y
    CONFIG_VIRTIO_BLK=y
    CONFIG_VIRTIO_BLK_SCSI=y
    CONFIG_VIRTIO_CONSOLE=y
    CONFIG_VIRTIO_INPUT=y
    CONFIG_VIRTIO_NET=y
    CONFIG_VIRTIO_PCI=y
    CONFIG_VIRTIO_PCI_LEGACY=y
EOF

RUN <<EOF
    cd /opt/linux/linux-5.4
    make -j$(nproc) bzImage
    ln -sf $PWD/arch/x86/boot/bzImage ../bzImage
    ln -sf $PWD/vmlinux ../vmlinux
EOF

################################################################################

FROM builder as builder-gdb

RUN <<EOF
    mkdir /opt/gdb
    wget -O - https://ftp.gnu.org/gnu/gdb/gdb-11.1.tar.gz | tar xzC /opt/gdb
    cd /opt/gdb/gdb-11.1
    mkdir build
    cd build
    ../configure --prefix=/usr --with-python=/usr/bin/python3
    make -j$(nproc)
    make install
EOF

RUN <<EOF
    git clone --recurse-submodules https://github.com/pwndbg/pwndbg /opt/pwndbg
    cd /opt/pwndbg
    ./setup.sh
    git clone https://github.com/hugsy/gef /opt/gef
    git clone https://github.com/jerdna-regeiz/splitmind /opt/splitmind
EOF

################################################################################

FROM essentials as builder-code-server

RUN <<EOF
    curl -fsSL https://code-server.dev/install.sh | /bin/sh /dev/stdin
    mkdir -p /opt/code-server/extensions
    code-server --extensions-dir=/opt/code-server/extensions --install-extension ms-python.python
EOF

WORKDIR /usr/lib/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin

RUN mv rg rg.orig

COPY <<EOF ./rg
#!/usr/bin/python

import sys
import os

sys.argv[0] += ".orig"
if "--follow" in sys.argv:
    sys.argv.remove("--follow")
os.execv(sys.argv[0], sys.argv)
EOF

RUN chmod +x rg

################################################################################

FROM builder as builder-tcpdump
RUN <<EOF
    git clone https://github.com/the-tcpdump-group/tcpdump /opt/tcpdump
    cd /opt/tcpdump
    ./autogen.sh
    ./configure
    make install
EOF

FROM builder as builder-capstone
RUN <<EOF
    git clone https://github.com/aquynh/capstone /opt/capstone
    cd /opt/capstone
    ./make.sh
    ./make.sh install
    ln -sf /lib/libcapstone.so /lib/libcapstone.so.3
EOF

FROM builder as builder-radare2
RUN <<EOF
    git clone https://github.com/radareorg/radare2 /opt/radare2
    cd /opt/radare2
    sys/install.sh
EOF

FROM builder as builder-aflplusplus
RUN <<EOF
    git clone https://github.com/aflplusplus/aflplusplus /opt/aflplusplus
    cd /opt/aflplusplus
    make distrib
    make install
EOF

FROM builder as builder-rappel
RUN <<EOF
    git clone https://github.com/yrp604/rappel /opt/rappel
    cd /opt/rappel
    make
    cp bin/rappel /usr/bin/rappel
EOF

FROM builder as builder-rp
RUN <<EOF
    wget https://github.com/0vercl0k/rp/releases/download/v2.0.2/rp-lin-x64 -O /usr/bin/rp++
    chmod +x /usr/bin/rp++
EOF

FROM builder as builder-geckodriver
RUN <<EOF
    wget -q -O - https://github.com/mozilla/geckodriver/releases/download/v0.32.0/geckodriver-v0.32.0-linux64.tar.gz | tar xvz -C /usr/local/bin
EOF

FROM builder as builder-busybox
RUN <<EOF
    VERSION="busybox-1.33.2"
    mkdir /opt/busybox && cd "$_"
    wget -q -O - "https://busybox.net/downloads/${VERSION}.tar.bz2" | tar xvj
    pushd "${VERSION}"
    make defconfig
    sed -e 's/.*CONFIG_STATIC .*/CONFIG_STATIC=y/' -i .config
    make -j$(nproc) install
    popd
    ln -s "${VERSION}/_install" /opt/busybox/fs
EOF

################################################################################

FROM essentials as builder-desktop-base

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install -yqq <<EOF
        novnc
        tigervnc-standalone-server
        websockify
        fluxbox
        eterm
EOF

################################################################################

FROM builder-desktop-base as builder-desktop-xfce

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install -yqq <<EOF && \
    apt-get -y remove --purge at-spi2-core tumbler gvfs-* && \
    apt-get -y autoremove
        dbus-x11
        mousepad
        xclip
        xfce4
        xfce4-terminal
EOF

# TODO: can we generate desktop data with cli ???
COPY desktop/xfce4 /usr/share/desktop-base/profiles/xdg-config/xfce4
COPY desktop/pwncollege_background.jpg /usr/share/backgrounds/

RUN rm /etc/xdg/autostart/*

################################################################################

FROM essentials as builder-desktop-reversing-tools

COPY desktop/angr-management.desktop /usr/share/applications/
COPY desktop/Ghidra.desktop /usr/share/applications/

RUN <<EOF
    wget -q -O - https://github.com/angr/angr-management/releases/download/nightly/angr-management-ubuntu-${UBUNTU_VERSION}.tar.gz | tar xvz -C /opt

    wget -q -O /tmp/ghidra.zip https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_10.3_build/ghidra_10.3_PUBLIC_20230510.zip
    unzip /tmp/ghidra.zip -d /tmp
    mv /tmp/ghidra_10.3_PUBLIC /opt/ghidra
    rm /tmp/ghidra.zip
EOF

# IDA Freeware: only permissible for free and open deployments of the dojo!
COPY desktop/ida64.desktop /usr/share/applications/
COPY desktop/ida.opt /opt/ida/ida.opt
RUN <<EOF
    if [ "$INSTALL_IDA" == "True" ]
    then
        wget -O /tmp/idafree80_linux.run https://out7.hex-rays.com/files/idafree80_linux.run
        chmod 755 /tmp/idafree80_linux.run
        /tmp/idafree80_linux.run --optionfile /opt/ida/ida.opt
        rm /tmp/idafree80_linux.run /tmp/installbuilder_installer.log
    else
        rm /usr/share/applications/ida64.desktop
        rm -rf /opt/ida
    fi
EOF

################################################################################

FROM essentials as builder-tools-apt

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install -yqq <<EOF
        arping
        binutils
        binutils-aarch64-linux-gnu
        binwalk
        bsdmainutils
        bsdutils
        debianutils
        diffutils
        ed
        elfutils
        emacs
        ethtool
        exiftool
        expect
        fish
        findutils
        firefox
        gdb
        gdb-multiarch
        genisoimage
        gnupg-utils
        hexedit
        iproute2
        iputils-ping
        ipython3
        keyutils
        kmod
        ltrace
        nano
        net-tools
        netcat-openbsd
        nmap
        openssh-server
        parallel
        patchelf
        pcaputils
        pcre2-utils
        psutils
        python3-ipdb
        qemu-system-x86
        rsync
        screen
        silversearcher-ag
        strace
        tmux
        whiptail
        wireshark
        gedit
        fortune
        zsh
EOF

################################################################################

FROM builder as builder-tools-pip

RUN xargs pip install --force-reinstall <<EOF
    angr
    asteval
    flask
    git+https://github.com/Gallopsled/pwntools#egg=pwntools
    git+https://github.com/secdev/scapy#egg=scapy
    jupyter
    psutil
    pycryptodome
    r2pipe
    requests
    selenium
EOF

RUN ln -sf /usr/bin/ipython3 /usr/bin/ipython

################################################################################

FROM builder-essentials as builder-pwn.college

RUN mkdir /opt/pwn.college
COPY docker-initialize.sh /opt/pwn.college/docker-initialize.sh
COPY docker-entrypoint.d /opt/pwn.college/docker-entrypoint.d
COPY docker-entrypoint.sh /opt/pwn.college/docker-entrypoint.sh
COPY setuid_interpreter.c /opt/pwn.college/setuid_interpreter.c
COPY vm /opt/pwn.college/vm
COPY .tmux.conf /opt/pwn.college/.tmux.conf
COPY .gdbinit /opt/pwn.college/.gdbinit
COPY .radare2rc /opt/pwn.college/.radare2rc
COPY .pwn.conf /opt/pwn.college/.pwn.conf

RUN gcc /opt/pwn.college/setuid_interpreter.c -DSUID_PYTHON -o /opt/pwn.college/python && \
    gcc /opt/pwn.college/setuid_interpreter.c -DSUID_BASH -o /opt/pwn.college/bash && \
    gcc /opt/pwn.college/setuid_interpreter.c -DSUID_SH -o /opt/pwn.college/sh && \
    rm /opt/pwn.college/setuid_interpreter.c

################################################################################

FROM ubuntu:${UBUNTU_VERSION} as challenge-nano

SHELL ["/bin/bash", "-ceov", "pipefail"]

ENV LC_CTYPE=C.UTF-8

COPY --link --from=essentials / /
COPY --link --from=builder-pwn.college /opt/pwn.college /opt/pwn.college

RUN <<EOF
    ln -sf /opt/pwn.college/vm/vm /usr/local/bin/vm

    ln -sf /home/hacker/.tmux.conf /root/.tmux.conf
    ln -sf /home/hacker/.gdbinit /root/.gdbinit
    ln -sf /home/hacker/.radare2rc /root/.radare2rc
    ln -sf /home/hacker/.pwn.conf /root/.pwn.conf

    mkdir /challenge
    install -m 400 <(echo 'pwn.college{uninitialized}') /flag

    find / -xdev -type f -perm -4000 -exec chmod u-s {} \;

    chmod u+s /opt/pwn.college/python \
              /opt/pwn.college/bash \
              /opt/pwn.college/sh \
              /opt/pwn.college/vm/vm
EOF

RUN date > /opt/pwn.college/build

################################################################################

FROM challenge-nano as challenge-micro
COPY --link --from=builder-code-server / /

################################################################################

FROM challenge-micro as challenge-mini
COPY --link --from=builder-desktop-base / /

################################################################################

FROM challenge-mini as challenge-full

# TODO: probably extra slow to `COPY / /`
COPY --link --from=builder-essentials / /
COPY --link --from=builder / /
COPY --link --from=builder-kernel /opt/linux /opt/linux
COPY --link --from=builder-tcpdump / /
COPY --link --from=builder-capstone / /
COPY --link --from=builder-radare2 / /
COPY --link --from=builder-aflplusplus / /
COPY --link --from=builder-rappel / /
COPY --link --from=builder-rp / /
COPY --link --from=builder-geckodriver / /
COPY --link --from=builder-busybox / /
COPY --link --from=builder-desktop-xfce / /
COPY --link --from=builder-desktop-reversing-tools / /
COPY --link --from=builder-tools-apt / /
COPY --link --from=builder-gdb / /
COPY --link --from=builder-tools-pip / /

RUN cat >> /etc/ssh/ssh_config <<EOF
    StrictHostKeyChecking no
    UserKnownHostsFile=/dev/null
    LogLevel ERROR
EOF

RUN <<EOF
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/g' /etc/ssh/sshd_config
    sed -i 's/#PermitEmptyPasswords no/PermitEmptyPasswords yes/g' /etc/ssh/sshd_config
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/g' /etc/ssh/sshd_config
EOF

################################################################################

# legacy
FROM challenge-mini as challenge-minimal
FROM challenge-full as challenge

################################################################################

FROM ${DOJO_CHALLENGE} as challenge-final

RUN <<EOF
    if id ubuntu; then userdel -f -r ubuntu; fi
    useradd -s /bin/bash -m hacker
    passwd -d hacker
EOF

USER hacker
WORKDIR /home/hacker
