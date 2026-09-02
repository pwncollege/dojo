#!/bin/sh
set -e

ca_key_der=$(mktemp)
ca_key=$(mktemp)
trap 'rm -f "$ca_key_der" "$ca_key"' EXIT
{
    printf '\060\056\002\001\000\060\005\006\003\053\145\160\004\042\004\040'
    printf 'xpra-ca' | openssl dgst -sha256 -mac HMAC -macopt "key:$WORKSPACE_SECRET" -binary
} > "$ca_key_der"
openssl pkey -inform DER -in "$ca_key_der" -out "$ca_key"
openssl req -x509 -new -key "$ca_key" -subj /CN=dojo-xpra-ca -days 36500 -set_serial 1 \
    -addext basicConstraints=critical,CA:TRUE \
    -addext keyUsage=critical,keyCertSign,cRLSign \
    -addext subjectKeyIdentifier=hash \
    -out /run/dojo-xpra-ca.crt
chmod 444 /run/dojo-xpra-ca.crt
rm -f "$ca_key_der" "$ca_key"
trap - EXIT

suffix=".dev.conf"
[ "$DOJO_ENV" = "production" ] && suffix=".prod.conf"

for f in /etc/nginx/conf.d/*"$suffix"; do
    ln -sf "$f" "${f%$suffix}.conf"
done
