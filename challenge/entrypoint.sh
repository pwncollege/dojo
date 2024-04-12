#!/bin/sh -e

mkdir -p /run/dojo
exec >/run/dojo/entrypoint.log 2>&1

for script in /opt/pwn.college/entrypoint.d/*
do
	user=$(basename "$script" | cut -d_ -f2)
	echo "[*] running entrypoint script '$script' as user '$user'"
	su "$user" -c "$script"
done

exec /bin/tini -- /bin/sleep 6h
