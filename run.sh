#!/bin/sh

set -e

cd "$(dirname "$0")"

export $(cat config.env | xargs)

if [ -z "$(docker ps -q -f name=nginx-proxy)" ]; then
    docker run \
           --detach \
           --name nginx-proxy \
           --publish 80:80 \
           --publish 443:443 \
           --volume /etc/nginx/certs \
           --volume $PWD/conf/nginx/vhost.d:/etc/nginx/vhost.d \
           --volume /usr/share/nginx/html \
           --volume /var/run/docker.sock:/tmp/docker.sock:ro \
           jwilder/nginx-proxy
fi

if [ -z "$(docker ps -q -f name=nginx-proxy-letsencrypt)" ]; then
    docker run \
           --detach \
           --name nginx-proxy-letsencrypt \
           --volumes-from nginx-proxy \
           --volume /var/run/docker.sock:/var/run/docker.sock:ro \
           jrcs/letsencrypt-nginx-proxy-companion
    # --env "DEFAULT_EMAIL=example@example.com" \
fi

if ! docker network inspect autotest_network -f '{{range .Containers}}{{println .Name}}{{end}}' | grep -q nginx-proxy; then
    docker network connect "${PWN_COLLEGE_INSTANCE}_network" nginx-proxy
fi

cp -r CTFd_plugin/. CTFd/CTFd/plugins/CTFd-pwn-college-plugin/
docker-compose down
docker-compose up -d
docker-compose logs -f
