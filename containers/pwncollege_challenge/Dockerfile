FROM ubuntu:20.04

RUN rm /etc/dpkg/dpkg.cfg.d/excludes

ENV DEBIAN_FRONTEND noninteractive
ENV LC_CTYPE=C.UTF-8

RUN dpkg --add-architecture i386
RUN apt-get update && \
    dpkg -l | grep ^ii | cut -d' ' -f3 | grep -v '^libgcc-s1:amd64$' | xargs apt-get install -y --reinstall && \
    apt-get install -y sudo \
                       build-essential \
                       gcc-multilib \
                       g++-multilib \
                       clang \
                       llvm \
                       gdb \
                       gdb-multiarch \
                       python-is-python3 \
                       python3-dev \
                       python3-pip \
                       ipython3 \
                       default-jdk \
                       net-tools \
                       nasm \
                       cmake \
                       rubygems \
                       emacs \
                       vim \
                       nano \
                       tmux \
                       screen \
                       git \
                       binwalk \
                       strace \
                       ltrace \
                       autoconf \
                       socat \
                       netcat \
                       nmap \
                       wget \
                       tcpdump \
                       exiftool \
                       hexedit \
                       parallel \
                       patchelf \
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
                       flex \
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

RUN useradd -s /bin/bash -m ctf

RUN ln -s /usr/bin/ipython3 /usr/bin/ipython

RUN git clone https://github.com/aquynh/capstone /opt/capstone && cd /opt/capstone && ./make.sh && ./make.sh install

RUN git clone --branch=5.1.0 --depth=1 https://github.com/radareorg/radare2 /opt/radare2 && cd /opt/radare2 && sys/install.sh

RUN git clone https://github.com/aflplusplus/aflplusplus /opt/aflplusplus && cd /opt/aflplusplus && make distrib && make install

RUN pip install git+git://github.com/Gallopsled/pwntools.git#egg=pwntools jupyter angr r2pipe

RUN git clone https://github.com/pwndbg/pwndbg /opt/pwndbg && cd /opt/pwndbg && ./setup.sh
RUN git clone https://github.com/jerdna-regeiz/splitmind /opt/splitmind

RUN git clone https://github.com/hugsy/gef /opt/gef

RUN git clone https://github.com/yrp604/rappel /opt/rappel && cd /opt/rappel && make && cp bin/rappel /usr/bin/rappel

RUN wget https://github.com/0vercl0k/rp/releases/download/v2-beta/rp-lin-x64 -O /usr/bin/rp++ && chmod +x /usr/bin/rp++

RUN git clone https://github.com/pwncollege/all-binutils /opt/all-binutils

RUN git clone https://github.com/pwncollege/babyauto-crackmes /opt/babyauto-crackmes

# TODO: remove this after regenerating old capstone challenge
# TODO: or remove the src install if apt gets updated
RUN apt-get update && apt-get install -y libcapstone-dev

RUN mkdir /opt/pwn-college

COPY .tmux.conf /opt/pwn-college/
COPY .gdbinit /opt/pwn-college/
COPY .radare2rc /opt/pwn-college/

RUN ln -sf /opt/pwn-college/.tmux.conf /home/ctf/.tmux.conf
RUN ln -sf /opt/pwn-college/.gdbinit /home/ctf/.gdbinit
RUN ln -sf /opt/pwn-college/.radare2rc /home/ctf/.radare2rc

RUN ln -sf /home/ctf /root

RUN echo 'pwn_college{missing}' > /flag
RUN chmod 400 /flag

RUN find / -type f -perm -4000 | xargs -r chmod u-s
