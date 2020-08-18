FROM ubuntu:18.04

RUN rm /etc/dpkg/dpkg.cfg.d/excludes

ENV DEBIAN_FRONTEND noninteractive

RUN dpkg --add-architecture i386
RUN apt-get update && \
    dpkg -l | grep ^ii | cut -d' ' -f3 | xargs apt-get install -y --reinstall && \
    apt-get install -y sudo \
                       build-essential \
                       gcc-multilib \
                       g++-multilib \
                       gdb \
                       gdb-multiarch \
                       python-dev \
                       python3-dev \
                       python-pip \
                       python3-pip \
                       ipython \
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
		       libedit-dev

RUN useradd -s /bin/bash -m ctf

RUN rm /usr/bin/python
RUN ln -s /usr/bin/python3 /usr/bin/python

RUN rm /usr/bin/pip
RUN ln -s /usr/bin/pip3 /usr/bin/pip
RUN sed -i 's:#!/usr/bin/python:#!/usr/bin/python2:g' /usr/bin/pip2

RUN mv /usr/bin/ipython /usr/bin/ipython2
RUN ln -s /usr/bin/ipython3 /usr/bin/ipython
RUN sed -i 's/VERSION=""/VERSION="2"/g' /usr/bin/ipython2

RUN su ctf -c 'wget -q -O- https://github.com/hugsy/gef/raw/master/scripts/gef.sh | sh'
ENV LC_CTYPE=C.UTF-8

RUN pip2 install pwntools
RUN pip3 install git+https://github.com/Gallopsled/pwntools@dev3

RUN git clone https://github.com/yrp604/rappel /tmp/rappel && cd /tmp/rappel && make && cp bin/rappel /usr/bin/rappel

RUN pip install angr

RUN wget https://github.com/0vercl0k/rp/releases/download/v2-beta/rp-lin-x64 -O /usr/bin/rp++ && chmod +x /usr/bin/rp++

RUN find / -type f -perm -4000 | xargs -r chmod u-s

RUN mkdir /opt/pwn-college

RUN echo 'pwn_college{0000000000000000000000000000000000000000}' > /flag
RUN chmod 400 /flag
