#!/bin/sh
set -e

suffix=".dev.conf"
[ "$DOJO_ENV" = "production" ] && suffix=".prod.conf"

for f in /etc/nginx/conf.d/*"$suffix"; do
    ln -sf "$f" "${f%$suffix}.conf"
done
