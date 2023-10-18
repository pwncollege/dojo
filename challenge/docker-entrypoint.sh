#!/bin/sh -e

mkdir -p /tmp/.dojo
exec >/tmp/.dojo/entrypoint.log 2>&1

for SCRIPT in /opt/pwn.college/docker-entrypoint.d/*
do
	echo "[*] docker-entrypoint running script: $SCRIPT"
	"$SCRIPT"
done
