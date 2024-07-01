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

nix build ".#$DOJO_WORKSPACE" --out-link /out/nix/var/nix/profiles/default
nix copy -v --to /out --no-require-sigs ".#$DOJO_WORKSPACE"
EOF

RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
