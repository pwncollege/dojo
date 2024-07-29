FROM alpine

VOLUME /nix

RUN apk add --no-cache nix git

RUN cat >> /etc/nix/nix.conf <<EOF
experimental-features = nix-command flakes
auto-optimise-store = true
substituters = /out https://cache.nixos.org/
trusted-substituters = /out
EOF

RUN git clone --branch nixos-24.05 --depth 1 https://github.com/NixOS/nixpkgs.git /opt/nixpkgs-24.05

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
for suid_binary in "python-suid" "bash-suid" "sh-suid"; do
    chmod u+s "/nix/var/nix/profiles/default/bin/${suid_binary}"
done
nix copy --to /out --no-require-sigs ".#$DOJO_WORKSPACE"
EOF

RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
