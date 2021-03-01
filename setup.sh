#!/usr/bin/env bash

set -e

DIR="$(readlink -f $(dirname $0))"
INSTANCE=$1
NUM_USERS=256

if [ -z $1 ]; then
    echo "Usage: $0 <INSTANCE>"
    exit 1
fi


RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

color_echo ()
{
    echo -e "$1$2$NC"
}

cd $DIR

color_echo $YELLOW "[+] Install dependencies"

apt update
apt install -y python-is-python3 python3-dev python3-pip
if [ ! -x /usr/bin/docker ]; then
    wget -O - https://get.docker.io/ | sh
fi
python3 -m pip install docker docker-compose

git -C $DIR submodule update --init

color_echo $YELLOW "[+] Creating config file"

if [ ! -f config.env ]; then
    cat <<EOF >> config.env
COMPOSE_PROJECT_NAME=$INSTANCE
PWN_COLLEGE_INSTANCE=$INSTANCE
HOST_DATA_PATH=$DIR/.data
SECRET_KEY=$(openssl rand -hex 16)
VIRTUAL_HOST=${INSTANCE}.pwn.college
VIRTUAL_PORT=8000
LETSENCRYPT_HOST=${INSTANCE}.pwn.college
EOF
fi

export $(cat config.env | xargs)

color_echo $YELLOW "[+] Setting up homes"

mkdir -p $DIR/.data/homes
mkdir -p $DIR/.data/homes/data
mkdir -p $DIR/.data/homes/nosuid
for i in $(seq 0 $NUM_USERS); do
    if [ ! -d $DIR/.data/homes/data/$i ]; then
	cp -r /etc/skel $DIR/.data/homes/data/$i
	chown -R ubuntu:ubuntu $DIR/.data/homes/data/$i
    fi
    if [ ! -d $DIR/.data/homes/nosuid/$i ]; then
	mkdir -p $DIR/.data/homes/nosuid/$i
    fi
    if ! mount | grep -q $DIR/.data/homes/nosuid/$i; then
	mount -o bind,nosuid $DIR/.data/homes/data/$i $DIR/.data/homes/nosuid/$i
    fi
done

color_echo $YELLOW "[+] Setting up challenges"

mkdir -p $DIR/.data/challenges
for i in $(seq 0 $NUM_USERS); do
    mkdir -p $DIR/.data/challenges/$i
done
if [ ! -e $DIR/.data/challenges/global ]; then
    pushd $DIR/.data/challenges
    ln -s 0 global
    popd
fi

color_echo $YELLOW "[+] Configuring global resources"

sysctl -w kernel.pty.max=1048576
echo core >/proc/sys/kernel/core_pattern
chmod 666 /var/run/docker.sock

color_echo $YELLOW "[+] Setting up SSH"

if [ -z "$(getent passwd $INSTANCE)" ]; then
    useradd -m $INSTANCE
    usermod -aG docker $INSTANCE
fi

if ! grep -q "Match User $INSTANCE" /etc/ssh/sshd_config; then
    cat <<EOF >> /etc/ssh/sshd_config

Match User $INSTANCE
      AuthorizedKeysCommand $DIR/auth.py ${INSTANCE}_db $INSTANCE
      AuthorizedKeysCommandUser root
      X11Forwarding no
      AllowTcpForwarding no

EOF
    service ssh restart
fi

color_echo $YELLOW "[+] Pulling docker images"

docker pull pwncollege/pwncollege_challenge
docker pull pwncollege/pwncollege_kernel_challenge
docker pull jwilder/nginx-proxy
docker pull jrcs/letsencrypt-nginx-proxy-companion

color_echo $YELLOW "[+] Setup docker compose"

docker-compose build

if [ -z "$(docker network ls -q -f name=${INSTANCE}_network)" ]; then
    docker network create "${INSTANCE}_network"
fi
