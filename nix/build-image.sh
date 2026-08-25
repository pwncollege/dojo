#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
    echo "Usage: $0 IMAGE_NAME" >&2
    exit 1
fi

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

image_name="$1"
nix build --print-build-logs .#dojo-image

shopt -s nullglob
image_tarballs=(result/tarball/nixos-system-*.tar.xz)
shopt -u nullglob
if [ "${#image_tarballs[@]}" -ne 1 ]; then
    echo "Expected exactly one NixOS image at result/tarball/nixos-system-*.tar.xz" >&2
    exit 1
fi

nix_output="$(basename "$(readlink -f result)")"
existing_output="$(
    docker image inspect \
        --format '{{with .Config.Labels}}{{index . "org.pwncollege.dojo.nix-output"}}{{end}}' \
        "$image_name" 2>/dev/null || true
)"
if [ "$existing_output" = "$nix_output" ]; then
    echo "Image $image_name already contains $nix_output"
    exit 0
fi

docker import \
    --change 'CMD ["/init"]' \
    --change 'ENV LC_CTYPE=C.UTF-8' \
    --change 'ENV PATH=/run/wrappers/bin:/run/current-system/sw/bin' \
    --change 'EXPOSE 22 80 443 8001' \
    --change 'STOPSIGNAL SIGRTMIN+3' \
    --change 'WORKDIR /opt/pwn.college' \
    --change "LABEL org.pwncollege.dojo.nix-output=$nix_output" \
    "${image_tarballs[0]}" "$image_name"
