#!/bin/sh

DIR="$(readlink -f $(dirname $0))"

if [ ! -f "$DIR/data/config.env" ] && [ -z "$SETUP_HOSTNAME" ]; then
    echo "Error: instance not setup; rerun with SETUP_HOSTNAME environment variable!"
    exit 1
fi

docker build -t pwn.college .

docker kill pwn.college

docker run \
       --privileged \
       --detach \
       --rm \
       --volume $PWD/data/docker:/var/lib/docker \
       --volume $PWD/data:/opt/pwn.college/data \
       --publish 22:22 \
       --publish 80:80 \
       --publish 443:443 \
       --env SETUP_HOSTNAME="$SETUP_HOSTNAME" \
       --name pwn.college \
       pwn.college

docker exec pwn.college logs
