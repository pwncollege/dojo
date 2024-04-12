#!/bin/sh -e

mkdir -p /run/dojo
exec >/run/dojo/entrypoint.log 2>&1

echo "$DOJO_FLAG" > /flag
unset DOJO_FLAG

for script in /opt/pwn.college/entrypoint.d/*
do
	user=$(basename "$script" | cut -d_ -f2)
	echo "[*] running entrypoint script '$script' as user '$user'"
	su "$user" -c "$script"
done

exec /bin/tini -- /bin/sleep 6h
