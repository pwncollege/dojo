#!/bin/sh -e

for SCRIPT in /opt/pwn.college/docker-entrypoint.d/*
do
	echo "[*] docker-entrypoint running script: $SCRIPT"
	"$SCRIPT"
done
