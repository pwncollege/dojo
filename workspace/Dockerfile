FROM alpine:latest

RUN apk add --no-cache nix
RUN apk add --no-cache git
RUN cat >> /etc/nix/nix.conf <<EOF
experimental-features = nix-command flakes
accept-flake-config = true
substituters = https://cache.nixos.org/
EOF

COPY --chmod=755 <<'EOF' /docker-entrypoint.sh
#!/bin/sh -e

TIMESTAMP=$(date +%Y%m%d%H%M%S)
NIX_PROFILES_DIR=/nix/var/nix/profiles
NIX_PROFILE=${NIX_PROFILES_DIR}/dojo-workspace-${TIMESTAMP}
NIX_FLAKE_LOCK_FILE=/nix/var/nix/dojo-workspace-flake.lock

nix build ".#${DOJO_WORKSPACE:-default}" \
    --out-link "$NIX_PROFILE" \
    --reference-lock-file "$NIX_FLAKE_LOCK_FILE" \
    --output-lock-file "$NIX_FLAKE_LOCK_FILE" \
    --print-build-logs

SUID_FILE="$NIX_PROFILE/suid"
if [ -e "$SUID_FILE" ]; then
    while IFS= read -r path; do
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

ln -sfn "$NIX_PROFILE" "${NIX_PROFILES_DIR}/dojo-workspace"
echo "Updated profile to $NIX_PROFILE"

echo "Removing old profiles..."
find "$NIX_PROFILES_DIR" -maxdepth 1 -name 'dojo-workspace-*' -type l -mmin +600 -print -exec rm -f {} +
echo "Removed old profiles"

if  [ "$NIX_GARBAGE_COLLECT" = "true" ]; then
    echo "Garbage collecting..."
    nix-collect-garbage -d
    echo "Garbage collected"
fi
EOF

WORKDIR /workspace
COPY . .

ENTRYPOINT ["/docker-entrypoint.sh"]
