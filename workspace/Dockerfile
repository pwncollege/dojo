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

if [ -e /dev/kvm ]; then
    chmod 666 /dev/kvm
fi

nix build --print-build-logs ".#$DOJO_WORKSPACE" --out-link /out/nix/var/nix/profiles/default
nix copy --to /out --no-require-sigs ".#$DOJO_WORKSPACE"
for suid_binary in "python-suid" "bash-suid" "sh-suid" "windows"; do
    suid_binary_path=$(realpath "/out/nix/var/nix/profiles/default/bin/${suid_binary}")
    FILE="/out/${suid_binary_path}"
    if [ -e $FILE ]; then
        chmod u+s "$FILE"
    fi
done
EOF

RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
