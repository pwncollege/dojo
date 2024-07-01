FROM alpine

VOLUME /nix

RUN apk add --no-cache nix

RUN cat >> /etc/nix/nix.conf <<EOF
experimental-features = nix-command flakes
auto-optimise-store = true
substituters = /out https://cache.nixos.org/
trusted-substituters = /out
EOF

WORKDIR /workspace
COPY . .

ARG DOJO_WORKSPACE="default"
ENV DOJO_WORKSPACE="$DOJO_WORKSPACE"

RUN cat > /docker-entrypoint.sh <<'EOF'
#!/bin/sh
if [ ! -d /out ]; then
    echo "Missing /out directory; mount a directory to /out!" >&2
    exit 1
fi

nix copy --to /out --no-require-sigs ".#$DOJO_WORKSPACE"

env -i nix develop ".#$DOJO_WORKSPACE" -c bash -c '
    echo "#!$SHELL" > /out/nix/init
    export | grep "declare -x [A-Z_]*=" | sed -e "s|$TMP|/tmp|g" -e "s|/no-such-path|\$PATH|" >> /out/nix/init
    echo "exec \"\$@\"" >> /out/nix/init
    chmod +x /out/nix/init
'
EOF

RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
