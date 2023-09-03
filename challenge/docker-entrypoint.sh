#!/bin/sh -e

exec >/tmp/.startup_log 2>&1
chmod 600 /tmp/.startup_log

for SCRIPT in /opt/pwn.college/docker-entrypoint.d/*
do
	echo "[*] docker-entrypoint running script: $SCRIPT"
	"$SCRIPT"
done
