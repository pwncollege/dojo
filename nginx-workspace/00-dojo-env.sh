#!/bin/sh
set -e

suffix=".dev.conf"
[ "$DOJO_ENV" != "development" ] && suffix=".prod.conf"

for f in /etc/nginx/conf.d/*"$suffix"; do
    ln -sf "$f" "${f%$suffix}.conf"
done
