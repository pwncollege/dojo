# syntax=docker/dockerfile:1

ARG UBUNTU_VERSION=20.04
ARG DOJO_CHALLENGE=challenge-mini
ARG DEFAULT_INSTALL_SELECTION=yes
ARG INSTALL_KERNEL=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_TCPDUMP=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_CAPSTONE=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_RADARE2=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_AFL=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_RAPPEL=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_RP=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_GECKODRIVER=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_BURPSUITE=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_BUSYBOX=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_GLOW=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_DESKTOP_BASE=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_XFCE=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_VIRTIOFSD=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_IDA_FREE=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_BINJA_FREE=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_GHIDRA=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_ANGR_MANAGEMENT=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_GDB=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_TOOLS_PIP=${DEFAULT_INSTALL_SELECTION}
ARG INSTALL_TOOLS_APT=${DEFAULT_INSTALL_SELECTION}

FROM ubuntu:${UBUNTU_VERSION} as essentials

SHELL ["/bin/bash", "-ceov", "pipefail"]

ENV DEBIAN_FRONTEND noninteractive
ENV LC_CTYPE=C.UTF-8

RUN <<EOF
    rm -f /etc/apt/apt.conf.d/docker-clean
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

    (set +o pipefail; yes | unminimize)

    dpkg --add-architecture i386

    apt-get clean && rm -rf /var/lib/apt/lists/*
EOF

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install --no-install-recommends -yqq <<EOF && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
        ca-certificates
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
    apt-get update && xargs apt-get install --no-install-recommends -yqq <<EOF && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
        build-essential
EOF

################################################################################

FROM builder-essentials as builder

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install --no-install-recommends -yqq <<EOF && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
        autoconf
        bc
        bison
        clang
        cmake
        cpio
        openjdk-17-jdk
        flex
	dwarves
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
        p7zip-full
        apache2
        php-cgi
        mysql-server
        php-mysql
        libapache2-mod-php
EOF

################################################################################

FROM builder as builder-kernel-no
RUN mkdir /opt/linux
FROM builder as builder-kernel-yes

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

FROM builder-kernel-${INSTALL_KERNEL} as builder-kernel

################################################################################

FROM builder as builder-gdb-no
FROM builder as builder-gdb-yes

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
    git clone --depth 1 --recurse-submodules https://github.com/pwndbg/pwndbg /opt/pwndbg
    cd /opt/pwndbg
    ./setup.sh
    ln -sf /home/hacker/.gdbinit /root/.gdbinit

    git clone --depth 1 https://github.com/hugsy/gef /opt/gef
    git clone --depth 1 https://github.com/jerdna-regeiz/splitmind /opt/splitmind
EOF

FROM builder-gdb-${INSTALL_GDB} as builder-gdb

################################################################################

FROM essentials as builder-code-server

RUN <<EOF
    curl -fsSL https://code-server.dev/install.sh | /bin/sh /dev/stdin
    mkdir -p /opt/code-server/extensions
    code-server --extensions-dir=/opt/code-server/extensions --install-extension ms-python.python
    rm -rf /root/.cache/code-server
    rm -rf /root/.local/share/code-server
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

FROM builder as builder-tcpdump-no
FROM builder as builder-tcpdump-yes
RUN <<EOF
    git clone --depth 1 https://github.com/the-tcpdump-group/tcpdump /opt/tcpdump
    cd /opt/tcpdump
    ./autogen.sh
    ./configure
    make install
EOF
FROM builder-tcpdump-${INSTALL_TCPDUMP} as builder-tcpdump

FROM builder as builder-capstone-no
FROM builder as builder-capstone-yes
RUN <<EOF
    git clone --depth 1 https://github.com/capstone-engine/capstone /opt/capstone
    cd /opt/capstone
    make
    make install
EOF
FROM builder-capstone-${INSTALL_CAPSTONE} as builder-capstone

FROM builder as builder-radare2-no
FROM builder as builder-radare2-yes
RUN <<EOF
    git clone --depth 1 https://github.com/radareorg/radare2 /opt/radare2
    cd /opt/radare2
    sys/install.sh
EOF
FROM builder-radare2-${INSTALL_RADARE2} as builder-radare2

FROM builder as builder-aflplusplus-no
FROM builder as builder-aflplusplus-yes
RUN <<EOF
    git clone --depth 1 https://github.com/aflplusplus/aflplusplus /opt/aflplusplus
    cd /opt/aflplusplus
    make distrib
    make install
EOF
FROM builder-aflplusplus-${INSTALL_AFL} as builder-aflplusplus

FROM builder as builder-rappel-no
FROM builder as builder-rappel-yes
RUN <<EOF
    git clone --depth 1 https://github.com/yrp604/rappel /opt/rappel
    cd /opt/rappel
    make
    cp bin/rappel /usr/bin/rappel
EOF
FROM builder-rappel-${INSTALL_RAPPEL} as builder-rappel

FROM builder as builder-rp-no
FROM builder as builder-rp-yes
RUN <<EOF
    wget https://github.com/0vercl0k/rp/releases/download/v2.0.2/rp-lin-x64 -O /usr/bin/rp++
    chmod +x /usr/bin/rp++
EOF
FROM builder-rp-${INSTALL_RP} as builder-rp

FROM builder as builder-geckodriver-no
FROM builder as builder-geckodriver-yes
RUN <<EOF
    wget -q -O - https://github.com/mozilla/geckodriver/releases/download/v0.32.0/geckodriver-v0.32.0-linux64.tar.gz | tar xvz -C /usr/local/bin
EOF
FROM builder-geckodriver-${INSTALL_GECKODRIVER} as builder-geckodriver

FROM builder as builder-burpsuite-no
FROM builder as builder-burpsuite-yes
RUN <<EOF
    wget -q -O /tmp/burpsuite.sh https://portswigger.net/burp/releases/download?product=community\&version=2023.11.1.4\&type=Linux
    sh /tmp/burpsuite.sh -q
    rm /tmp/burpsuite.sh
EOF
FROM builder-burpsuite-${INSTALL_BURPSUITE} as builder-burpsuite

FROM builder as builder-busybox-no
FROM builder as builder-busybox-yes
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
FROM builder-busybox-${INSTALL_BUSYBOX} as builder-busybox

FROM builder as builder-glow-no
FROM builder as builder-glow-yes
RUN <<EOF
    VERSION="1.5.1"
    DEB_NAME="glow_${VERSION}_amd64.deb"
    pushd /tmp
    wget -q "https://github.com/charmbracelet/glow/releases/download/v${VERSION}/${DEB_NAME}"
    apt install "./${DEB_NAME}"
    rm "${DEB_NAME}"
    popd
EOF
FROM builder-glow-${INSTALL_GLOW} as builder-glow

FROM builder as builder-virtiofsd-no
RUN mkdir /opt/virtiofsd
FROM builder as builder-virtiofsd-yes
RUN <<EOF
    mkdir /opt/virtiofsd && cd "$_"
    wget -q -O ./build.zip "https://gitlab.com/virtio-fs/virtiofsd/-/jobs/artifacts/main/download?job=publish"
    unzip -p ./build.zip "$(zipinfo -1 ./build.zip | head -n1)" > ./virtiofsd
    rm -f ./build.zip
    chmod +x ./virtiofsd
EOF
FROM builder-virtiofsd-${INSTALL_VIRTIOFSD} as builder-virtiofsd

################################################################################

FROM essentials as builder-desktop-base-no
FROM essentials as builder-desktop-base-yes

ARG UBUNTU_VERSION=20.04
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    [ "${UBUNTU_VERSION}" == "20.04" ] && TGR=common || TGR=tools; \
    apt-get update && xargs apt-get install --no-install-recommends -yqq <<EOF && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
        novnc
        tigervnc-standalone-server
        tigervnc-$TGR
        websockify
        fluxbox
        xterm
EOF

FROM builder-desktop-base-${INSTALL_DESKTOP_BASE} as builder-desktop-base

################################################################################

FROM builder-desktop-base-no as builder-desktop-xfce-no
FROM builder-desktop-base-yes as builder-desktop-xfce-yes

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install -yqq <<EOF && \
    apt-get -y remove --purge at-spi2-core tumbler gvfs-* && \
    apt-get -y autoremove && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
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

FROM builder-desktop-xfce-${INSTALL_XFCE} as builder-desktop-xfce

################################################################################

FROM essentials as builder-desktop-angr-management-no
FROM essentials as builder-desktop-angr-management-yes

COPY desktop/angr-management.desktop /usr/share/applications/
ARG UBUNTU_VERSION=20.04
RUN <<EOF
    wget -q -O - https://github.com/angr/angr-management/releases/download/nightly/angr-management-ubuntu-${UBUNTU_VERSION}.tar.gz | tar xvz -C /opt
EOF

FROM builder-desktop-angr-management-${INSTALL_ANGR_MANAGEMENT} as builder-desktop-angr-management

################################################################################

FROM essentials as builder-desktop-ghidra-no
FROM essentials as builder-desktop-ghidra-yes

COPY desktop/Ghidra.desktop /usr/share/applications/
RUN <<EOF
    wget -q -O /tmp/ghidra.zip https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_10.3_build/ghidra_10.3_PUBLIC_20230510.zip
    unzip /tmp/ghidra.zip -d /tmp
    mv /tmp/ghidra_10.3_PUBLIC /opt/ghidra
    rm /tmp/ghidra.zip
EOF

FROM builder-desktop-ghidra-${INSTALL_GHIDRA} as builder-desktop-ghidra

################################################################################

FROM essentials as builder-desktop-ida-free-no
FROM essentials as builder-desktop-ida-free-yes

# IDA Freeware: only permissible for free and open deployments of the dojo!
COPY desktop/ida64.desktop /usr/share/applications/
COPY desktop/ida.opt /opt/ida/ida.opt
RUN <<EOF
    wget -O /tmp/idafree80_linux.run https://out7.hex-rays.com/files/idafree80_linux.run
    chmod 755 /tmp/idafree80_linux.run
    /tmp/idafree80_linux.run --optionfile /opt/ida/ida.opt
    rm /tmp/idafree80_linux.run /tmp/installbuilder_installer.log
EOF

FROM builder-desktop-ida-free-${INSTALL_IDA_FREE} as builder-desktop-ida-free

################################################################################

FROM essentials as builder-desktop-binja-free-no
FROM essentials as builder-desktop-binja-free-yes

COPY desktop/binary-ninja.desktop /usr/share/applications/
RUN <<EOF
    wget -O /tmp/BinaryNinja-free.zip https://cdn.binary.ninja/installers/BinaryNinja-free.zip
    unzip -d /opt /tmp/BinaryNinja-free.zip
    wget -O /opt/binaryninja/icon.png  https://binary.ninja/icons/android-chrome-192x192.png
    rm /tmp/BinaryNinja-free.zip
EOF

FROM builder-desktop-binja-free-${INSTALL_BINJA_FREE} as builder-desktop-binja-free

################################################################################

FROM essentials as builder-tools-apt-no
FROM essentials as builder-tools-apt-yes

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && xargs apt-get install --no-install-recommends -yqq <<EOF && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
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
        gcc-aarch64-linux-gnu
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
        libc6-arm64-cross
        libc6-dev-arm64-cross
        less
        ltrace
        nano
        neovim
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
        qemu-user
        qemu-system-x86
        qemu-utils
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
        zip
EOF

FROM builder-tools-apt-${INSTALL_TOOLS_APT} as builder-tools-apt

################################################################################

FROM builder as builder-tools-pip-no
FROM builder as builder-tools-pip-yes

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

FROM builder-tools-pip-${INSTALL_TOOLS_PIP} as builder-tools-pip

################################################################################

FROM builder-essentials as builder-pwn.college

RUN mkdir /opt/pwn.college
COPY docker-initialize.sh /opt/pwn.college/docker-initialize.sh
COPY docker-entrypoint.d /opt/pwn.college/docker-entrypoint.d
COPY docker-entrypoint.sh /opt/pwn.college/docker-entrypoint.sh
COPY setuid_interpreter.c /opt/pwn.college/setuid_interpreter.c
COPY bash.bashrc /opt/pwn.college/bash.bashrc
COPY vm /opt/pwn.college/vm
COPY windows /opt/pwn.college/windows
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
    ln -sf /bin/bash /opt/pwn.college/ssh-entrypoint
    ln -sf /opt/pwn.college/vm/vm /usr/local/bin/vm
    ln -sf /opt/pwn.college/windows/windows /usr/local/bin/windows

    ln -sf /home/hacker/.tmux.conf /root/.tmux.conf
    ln -sf /home/hacker/.gdbinit /root/.gdbinit
    ln -sf /home/hacker/.radare2rc /root/.radare2rc
    ln -sf /home/hacker/.pwn.conf /root/.pwn.conf

    mkdir /challenge
    install -m 400 <(echo 'pwn.college{uninitialized}') /flag
EOF

################################################################################

FROM challenge-nano as challenge-micro
COPY --link --from=builder-code-server / /

################################################################################

FROM challenge-micro as challenge-mini
COPY --link --from=builder-desktop-base / /

################################################################################

FROM challenge-mini as challenge-granular

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
COPY --link --from=builder-burpsuite / /
COPY --link --from=builder-busybox / /
COPY --link --from=builder-glow / /
COPY --link --from=builder-desktop-xfce / /
COPY --link --from=builder-virtiofsd /opt/virtiofsd /opt/virtiofsd
COPY --link --from=builder-desktop-ida-free / /
COPY --link --from=builder-desktop-binja-free / /
COPY --link --from=builder-desktop-ghidra / /
COPY --link --from=builder-desktop-angr-management / /
COPY --link --from=builder-gdb / /
COPY --link --from=builder-tools-pip / /
COPY --link --from=builder-tools-apt / /

################################################################################

FROM challenge-mini as challenge-full

# here, everything is installed except for
# IDA, which still uses the INSTALL_IDA_FREE parameter
# binja, which uses the INSTALL_BINJA_FREE parameter

# TODO: probably extra slow to `COPY / /`
COPY --link --from=builder-essentials / /
COPY --link --from=builder / /
COPY --link --from=builder-kernel-yes /opt/linux /opt/linux
COPY --link --from=builder-tcpdump-yes / /
COPY --link --from=builder-capstone-yes / /
COPY --link --from=builder-radare2-yes / /
COPY --link --from=builder-aflplusplus-yes / /
COPY --link --from=builder-rappel-yes / /
COPY --link --from=builder-rp-yes / /
COPY --link --from=builder-geckodriver-yes / /
COPY --link --from=builder-burpsuite-yes / /
COPY --link --from=builder-busybox-yes / /
COPY --link --from=builder-glow-yes / /
COPY --link --from=builder-desktop-xfce-yes / /
COPY --link --from=builder-virtiofsd-yes /opt/virtiofsd /opt/virtiofsd
COPY --link --from=builder-desktop-ida-free / /
COPY --link --from=builder-desktop-binja-free / /
COPY --link --from=builder-desktop-ghidra-yes / /
COPY --link --from=builder-desktop-angr-management-yes / /
COPY --link --from=builder-gdb-yes / /
COPY --link --from=builder-tools-pip-yes / /
COPY --link --from=builder-tools-apt-yes / /

################################################################################

# legacy
FROM challenge-mini as challenge-minimal
FROM challenge-full as challenge

################################################################################

FROM ${DOJO_CHALLENGE} as challenge-final

RUN <<EOF
    if [ -f /etc/ssh/ssh_config ]
    then
        echo "StrictHostKeyChecking no" >> /etc/ssh/ssh_config
        echo "UserKnownHostsFile=/dev/null" >> /etc/ssh/ssh_config
        echo "LogLevel ERROR" >> /etc/ssh/ssh_config
    fi
EOF

RUN <<EOF
    if [ -f /etc/ssh/sshd_config ]
    then
        sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/g' /etc/ssh/sshd_config
        sed -i 's/#PermitEmptyPasswords no/PermitEmptyPasswords yes/g' /etc/ssh/sshd_config
        sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/g' /etc/ssh/sshd_config
    fi
EOF

RUN <<EOF
    if id ubuntu; then userdel -f -r ubuntu; fi

    useradd -s /bin/bash -m hacker
    passwd -d hacker

    echo -e '\n[ "$UID" -eq 1000 ] && . /opt/pwn.college/bash.bashrc' >> /etc/bash.bashrc

    find / -xdev -type f -perm -4000 -exec chmod u-s {} \;

    chmod u+s /opt/pwn.college/python \
              /opt/pwn.college/bash \
              /opt/pwn.college/sh \
              /opt/pwn.college/vm/vm \
              /opt/pwn.college/windows/windows

    date > /opt/pwn.college/build
EOF

USER hacker
WORKDIR /home/hacker
