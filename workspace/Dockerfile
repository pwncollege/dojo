FROM alpine

VOLUME /nix

RUN apk add --no-cache nix git

RUN cat >> /etc/nix/nix.conf <<EOF
experimental-features = nix-command flakes
substituters = /out https://cache.nixos.org/
trusted-substituters = /out
EOF

RUN <<EOF
git clone --branch nixos-24.11 --depth 1 https://github.com/NixOS/nixpkgs.git /opt/nixpkgs-24.11
git clone --branch pwncollege-dojo-backports --depth 1 https://github.com/spencerpogo/nixpkgs.git /opt/nixpkgs-backports
EOF

WORKDIR /workspace
COPY . .

ARG DOJO_WORKSPACE="default"
ENV DOJO_WORKSPACE="$DOJO_WORKSPACE"

RUN cat > /docker-entrypoint.sh <<'EOF'
#!/bin/sh -e
if [ ! -d /out ]; then
    echo "Missing /out directory; mount a directory to /out!" >&2
    exit 1
fi

nix build --print-build-logs ".#$DOJO_WORKSPACE" --out-link /out/nix/var/nix/profiles/default
nix copy --to /out --no-require-sigs ".#$DOJO_WORKSPACE"

SUID_FILE="/out/nix/var/nix/profiles/default/suid"
if [ -e "$SUID_FILE" ]; then
    while IFS= read -r path; do
        path="/out/$path"
        if [ -e "$path" ]; then
            echo "Setting SUID bit on $path"
            chmod u+s "$path"
        else
            echo "Warning: file not found: $path" >&2
        fi
    done < "$SUID_FILE"
else
    echo "Warning: SUID file not found: $SUID_FILE" >&2
fi
EOF

RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
