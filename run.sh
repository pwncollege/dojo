#!/bin/sh

cd "$(dirname "$0")"

cp -r CTFd_plugin/. CTFd/CTFd/plugins/CTFd-pwn-college-plugin/
docker-compose down
docker-compose up -d
docker-compose logs -f
