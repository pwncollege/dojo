#!/bin/bash -e

DIR="$(readlink -f $(dirname $0))"

if [ "$1" == "build" ]
then
        docker build -t pwn.college .
elif [ "$1" == "run" ]
then
        $0 stop

        docker run \
                --privileged \
                --detach \
                --rm \
                --volume "$DIR"/data/docker:/var/lib/docker \
                --volume "$DIR"/data:/opt/pwn.college/data \
                --volume "$DIR"/dojo_plugin:/opt/CTFd/CTFd/plugins/dojo_plugin:ro \
                --volume "$DIR"/dojo_theme:/opt/CTFd/CTFd/themes/dojo_theme:ro \
                --publish "${SSH_PORT:-22}":22 \
                --publish "${HTTP_PORT:-80}":80 \
                --publish "${HTTPS_PORT:-443}":443 \
                --env SETUP_HOSTNAME="$SETUP_HOSTNAME" \
                --hostname dojo \
                --name pwn.college \
                pwn.college

        docker exec pwn.college logs
elif [ "$1" == "stop" ]
then
        while docker ps | awk '{print $NF}' | grep -q pwn.college
        do
                docker kill pwn.college || sleep 1
        done
elif [ "$1" == "logs" ]
then
        docker exec -it pwn.college docker logs -f "${2-ctfd}"
elif [ "$1" == "update" ]
then
        git -C "$DIR" pull
        git -C "$DIR"/data/dojos pull

        docker exec -it pwn.college docker stop ctfd
        docker exec -it pwn.college docker start ctfd
fi
