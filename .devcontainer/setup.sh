#!/bin/sh

rm /usr/lib/tmpfiles.d/tmp.conf

mkdir /etc/systemd/system/pwn.college.service.d
echo '[Service]' > /etc/systemd/system/pwn.college.service.d/devcontainer.conf
find /tmp -type f -path "*/devcontainers-*/env-loginInteractiveShell.json" -exec jq -r 'to_entries | .[] | "Environment=\(.key)=\(.value | @sh)"' {} \; >> /etc/systemd/system/pwn.college.service.d/devcontainer.conf
