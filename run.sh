#!/bin/sh

DIR="$(readlink -f $(dirname $0))"

docker build -t pwn.college .

docker kill pwn.college

docker run \
       --privileged \
       --detach \
       --rm \
       --volume $DIR/data/docker:/var/lib/docker \
       --volume $DIR/data:/opt/pwn.college/data \
       --volume $DIR/dojo_plugin:/opt/pwn.college/CTFd/CTFd/plugins/dojo_plugin:ro \
       --volume $DIR/dojo_theme:/opt/pwn.college/CTFd/CTFd/themes/dojo_theme:ro \
       --publish ${SSH_PORT:-22}:22 \
       --publish ${HTTP_PORT:-80}:80 \
       --publish ${HTTPS_PORT:-443}:443 \
       --env SETUP_HOSTNAME="$SETUP_HOSTNAME" \
       --hostname dojo \
       --name pwn.college \
       pwn.college

docker exec pwn.college logs
