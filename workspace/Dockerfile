FROM alpine:latest

RUN apk add --no-cache nix
RUN apk add --no-cache git jq
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

nix build ".#${DOJO_WORKSPACE:-default}" \
    --out-link "$NIX_PROFILE" \
    --no-update-lock-file \
    --print-build-logs

inputs=$(nix flake archive --json --no-update-lock-file .)
inputs=$(printf '%s\n' "$inputs" | jq -c '[.. | objects | .path // empty] | unique')
input_root=$(DOJO_WORKSPACE_INPUTS="$inputs" nix eval --raw --impure --expr '
    builtins.toFile "dojo-workspace-inputs" (builtins.toJSON (
        map builtins.storePath (builtins.fromJSON (builtins.getEnv "DOJO_WORKSPACE_INPUTS"))
    ))
')
nix-store --realise "$input_root" --add-root "${NIX_PROFILE}-inputs" >/dev/null

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
cutoff=$(($(date +%s) - 72 * 60 * 60))
profiles=$(find "$NIX_PROFILES_DIR" -maxdepth 1 -name 'dojo-workspace-*' ! -name '*-inputs' ! -path "$NIX_PROFILE" -type l)
position=1
for profile in $(printf '%s\n' "$profiles" | sort -r); do
    position=$((position + 1))
    modified=$(stat -c %Y "$profile")
    if [ "$position" -gt 5 ] || [ "$modified" -lt "$cutoff" ]; then
        echo "$profile"
        rm -f "$profile" "${profile}-inputs"
    fi
done
echo "Removed old profiles"

echo "Garbage collecting..."
nix-store --gc
echo "Garbage collected"
EOF

WORKDIR /workspace
COPY . .

ENTRYPOINT ["/docker-entrypoint.sh"]
