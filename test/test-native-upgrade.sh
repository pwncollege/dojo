#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "Usage: $0 LEGACY_SOURCE NATIVE_SOURCE DATA_ROOT" >&2
    exit 1
fi

legacy_source="$(realpath "$1")"
native_source="$(realpath "$2")"
data_root="$3"
mkdir -p "$data_root"
data_root="$(realpath "$data_root")"
if [ -n "$(find "$data_root" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "Transition data root must be empty: $data_root" >&2
    exit 1
fi

run_token="${TRANSITION_RUN_ID:-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-$$}}"
run_token="$(printf '%s' "$run_token" | tr -c 'A-Za-z0-9_.-' '-')"
outer_container="dojo-transition-$run_token"
legacy_image="dojo-transition-legacy-$run_token"
native_image="dojo-transition-native-$run_token"
sentinel_value=compose-to-nixos
learner_container=user_424242

cleanup() {
    status=$?
    trap - EXIT INT TERM
    set +e
    if [ "$status" -ne 0 ] && docker inspect "$outer_container" >/dev/null 2>&1; then
        docker logs "$outer_container"
        docker exec "$outer_container" systemctl --failed --no-pager
        docker exec "$outer_container" journalctl -b --no-pager -n 1000
    fi
    docker rm --force "$outer_container" >/dev/null 2>&1
    docker image rm "$legacy_image" "$native_image" >/dev/null 2>&1
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

test -f "$legacy_source/docker-compose.yml"
test -f "$legacy_source/Dockerfile"
test ! -f "$native_source/docker-compose.yml"
test -f "$native_source/flake.nix"

docker build \
    --label "org.pwncollege.dojo.transition=$run_token" \
    --tag "$legacy_image" \
    "$legacy_source"
docker run \
    --name "$outer_container" \
    --label "org.pwncollege.dojo.transition=$run_token" \
    --privileged \
    --volume "$legacy_source:/opt/pwn.college" \
    --volume "$data_root:/data:shared" \
    --detach \
    "$legacy_image"
docker exec "$outer_container" dojo wait

legacy_config_files="$(
    docker exec "$outer_container" docker inspect \
        --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' ctfd
)"
printf '%s\n' "$legacy_config_files" | tr ',' '\n' | grep -Fx /opt/pwn.college/docker-compose.yml

docker exec "$outer_container" sh -c "printf '%s\n' '$sentinel_value' > /data/transition-ci-state"
docker exec "$outer_container" dojo db --set ON_ERROR_STOP=1 --command \
    "CREATE TABLE transition_ci (value text PRIMARY KEY); INSERT INTO transition_ci VALUES ('$sentinel_value');"
docker exec "$outer_container" docker create \
    --name "$learner_container" \
    --label dojo.user_id=424242 \
    busybox:uclibc /bin/true
legacy_image_id="$(
    docker exec "$outer_container" docker image inspect \
        --format '{{.Id}}' busybox:uclibc
)"
legacy_secret="$(
    docker exec "$outer_container" bash -c '. /data/config.env; printf %s "$SECRET_KEY"'
)"
declare -A legacy_host_key_fingerprints
for key_type in ed25519 ecdsa rsa; do
    legacy_host_key_fingerprints[$key_type]="$(
        docker exec "$outer_container" ssh-keygen -lf \
            "/data/ssh_host_keys/ssh_host_${key_type}_key.pub" | awk '{print $2}'
    )"
done
docker exec "$outer_container" sync

docker kill "$outer_container"
docker rm "$outer_container"
docker image rm "$legacy_image"

(
    cd "$native_source"
    ./nix/build-image.sh "$native_image"
)
docker run \
    --name "$outer_container" \
    --label "org.pwncollege.dojo.transition=$run_token" \
    --privileged \
    --volume "$native_source:/opt/pwn.college" \
    --volume "$data_root:/data:shared" \
    --detach \
    "$native_image"
docker exec "$outer_container" dojo wait

docker exec "$outer_container" systemctl is-active --quiet dojo.target dojo-ready.target
docker exec "$outer_container" sh -c "test \"\$(cat /data/transition-ci-state)\" = '$sentinel_value'"
docker exec "$outer_container" sh -c \
    "grep -Fx 'DOJO_CONFIG_VERSION=1' /data/config.env && grep -Fx 'DB_HOST=/run/postgresql' /data/config.env"

native_secret="$(
    docker exec "$outer_container" bash -c '. /data/config.env; printf %s "$SECRET_KEY"'
)"
test "$native_secret" = "$legacy_secret"

for key_type in ed25519 ecdsa rsa; do
    native_fingerprint="$(
        docker exec "$outer_container" ssh-keygen -lf \
            "/data/ssh_host_keys/ssh_host_${key_type}_key.pub" | awk '{print $2}'
    )"
    test "$native_fingerprint" = "${legacy_host_key_fingerprints[$key_type]}"
done

database_value="$(
    docker exec "$outer_container" dojo db --tuples-only --no-align --command \
        'SELECT value FROM transition_ci;'
)"
test "$database_value" = "$sentinel_value"

native_image_id="$(
    docker exec "$outer_container" docker image inspect \
        --format '{{.Id}}' busybox:uclibc
)"
test "$native_image_id" = "$legacy_image_id"
test "$(
    docker exec "$outer_container" docker inspect \
        --format '{{index .Config.Labels "dojo.user_id"}}' "$learner_container"
)" = 424242

retired_containers="$(
    docker exec "$outer_container" docker ps --all --quiet --no-trunc \
        --filter label=com.docker.compose.project.working_dir=/opt/pwn.college
)"
test -z "$retired_containers"

echo "Compose-to-NixOS persisted-state upgrade succeeded"
