FROM ubuntu:20.04

RUN rm /etc/dpkg/dpkg.cfg.d/excludes

ENV DEBIAN_FRONTEND noninteractive

RUN dpkg --add-architecture i386
RUN apt-get update && \
    dpkg -l | grep ^ii | cut -d' ' -f3 | grep -v '^libgcc-s1:amd64$' | xargs apt-get install -y --reinstall && \
    apt-get install -y sudo \
                       build-essential \
                       gcc-multilib \
                       g++-multilib \
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
                       libtool-bin \
                       bison \
                       libini-config-dev \
                       libssl-dev \
                       libffi-dev \
                       libglib2.0-dev \
                       libc6:i386 \
                       libncurses5:i386 \
                       libstdc++6:i386 \
                       libc6-dev-i386 \
                       libcapstone-dev \
                       libseccomp-dev \
        	       libedit-dev

RUN yes | unminimize

RUN useradd -s /bin/bash -m ctf

RUN ln -s /usr/bin/pip3 /usr/bin/pip
RUN ln -s /usr/bin/ipython3 /usr/bin/ipython

RUN pip install pwntools angr

RUN su ctf -c 'wget -q -O- https://github.com/hugsy/gef/raw/master/scripts/gef.sh | sh'
ENV LC_CTYPE=C.UTF-8

RUN git clone https://github.com/yrp604/rappel /tmp/rappel && cd /tmp/rappel && make && cp bin/rappel /usr/bin/rappel

RUN wget https://github.com/0vercl0k/rp/releases/download/v2-beta/rp-lin-x64 -O /usr/bin/rp++ && chmod +x /usr/bin/rp++

RUN find / -type f -perm -4000 | xargs -r chmod u-s

RUN mkdir /opt/pwn-college

RUN echo 'pwn_college{0000000000000000000000000000000000000000}' > /flag
RUN chmod 400 /flag
