#!/bin/bash -ex

cd $(dirname "${BASH_SOURCE[0]}")/..

REPO_DIR=$(basename "$PWD")
DEFAULT_CONTAINER_NAME="local-${REPO_DIR}"

function usage {
	set +x
	echo "Usage: $0 [-r DB_BACKUP ] [ -c DOJO_CONTAINER ] [ -D DOCKER_DIR ] [ -W WORKSPACE_DIR ] [ -T ] [ -p ] [ -e ENV_VAR=value ] [ -b ]"
	echo ""
	echo "	-r	full path to db backup to restore"
	echo "	-c	the name of the dojo container (default: local-<dirname>)"
	echo "	-D	specify a directory for /data/docker (to avoid rebuilds)"
	echo "	-W	specify a directory for /data/workspace (to avoid rebuilds)"
	echo "	-T	don't run tests"
	echo "	-p	export ports (80->80, 443->443, 22->2222)"
	echo "	-e	set environment variable (can be used multiple times)"
	echo "	-b	build the Docker image locally (tag: same as container name)"
	exit
}

VOLUME_ARGS=()
ENV_ARGS=( )
DB_RESTORE=""
DOJO_CONTAINER="$DEFAULT_CONTAINER_NAME"
TEST=yes
DOCKER_DIR=""
WORKSPACE_DIR=""
EXPORT_PORTS=no
BUILD_IMAGE=no
while getopts "r:c:he:TD:W:pb" OPT
do
	case $OPT in
		r) DB_RESTORE="$OPTARG" ;;
		c) DOJO_CONTAINER="$OPTARG" ;;
		T) TEST=no ;;
		D) DOCKER_DIR="$OPTARG" ;;
		W) WORKSPACE_DIR="$OPTARG" ;;
		e) ENV_ARGS+=("-e" "$OPTARG") ;;
		p) EXPORT_PORTS=yes ;;
		b) BUILD_IMAGE=yes ;;
		h) usage ;;
		?)
			OPTIND=$(($OPTIND-1))
			break
			;;
	esac
done
shift $((OPTIND-1))

WORKDIR=$(mktemp -d /tmp/local-data-${DOJO_CONTAINER}-XXXXXX)
# Prepend the base volumes to the array
VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$WORKDIR:/data:shared" "${VOLUME_ARGS[@]}")

export DOJO_CONTAINER
docker kill "$DOJO_CONTAINER" 2>/dev/null || echo "No $DOJO_CONTAINER container to kill."
docker rm "$DOJO_CONTAINER" 2>/dev/null || echo "No $DOJO_CONTAINER container to remove."
while docker ps -a | grep "$DOJO_CONTAINER"; do sleep 1; done

# freaking bad unmount
sleep 1
mount | grep /tmp/local-data-${DOJO_CONTAINER}- | sed -e "s/.* on //" | sed -e "s/ .*//" | tac | while read ENTRY
do
	sudo umount "$ENTRY"
done

if [ -n "$DOCKER_DIR" ]
then
	VOLUME_ARGS+=( "-v" "$DOCKER_DIR:/data/docker" )
	sudo rm -rf $DOCKER_DIR/{containers,volumes}
fi
[ -n "$WORKSPACE_DIR" ] && VOLUME_ARGS+=( "-v" "$WORKSPACE_DIR:/data/workspace:shared" )

IMAGE_NAME="pwncollege/dojo"
if [ "$BUILD_IMAGE" == "yes" ]; then
	echo "Building Docker image with tag: $DOJO_CONTAINER"
	docker build -t "$DOJO_CONTAINER" . || exit 1
	IMAGE_NAME="$DOJO_CONTAINER"
fi

PORT_ARGS=()
if [ "$EXPORT_PORTS" == "yes" ]; then
	PORT_ARGS+=("-p" "80:80" "-p" "443:443" "-p" "2222:22")
fi

docker run --rm --privileged -d "${VOLUME_ARGS[@]}" "${ENV_ARGS[@]}" "${PORT_ARGS[@]}" --name "$DOJO_CONTAINER" "$IMAGE_NAME" || exit 1

CONTAINER_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$DOJO_CONTAINER")
export DOJO_URL="http://${CONTAINER_IP}"

echo "Container IP: $CONTAINER_IP"
echo "DOJO_URL: $DOJO_URL"

# fix the insane routing thing
read -a GW <<<$(ip route show default)
read -a NS <<<$(docker exec "$DOJO_CONTAINER" cat /etc/resolv.conf | grep nameserver)
docker exec "$DOJO_CONTAINER" ip route add "${GW[2]}" via 172.17.0.1
docker exec "$DOJO_CONTAINER" ip route add "${NS[1]}" via 172.17.0.1 || echo "Failed to add nameserver route"

docker exec "$DOJO_CONTAINER" dojo wait
if [ -n "$DB_RESTORE" ]
then
	BASENAME=$(basename $DB_RESTORE)
	docker exec "$DOJO_CONTAINER" mkdir -p /data/backups/
	[ -f "$DB_RESTORE" ] && docker cp "$DB_RESTORE" "$DOJO_CONTAINER":/data/backups/"$BASENAME"
	docker exec "$DOJO_CONTAINER" dojo restore "$BASENAME"
fi

until curl -Ls "${CONTAINER_IP}" | grep -q pwn; do sleep 1; done

docker exec "$DOJO_CONTAINER" docker pull pwncollege/challenge-simple
docker exec "$DOJO_CONTAINER" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy

[ "$TEST" == "yes" ] && MOZ_HEADLESS=1 DOJO_URL="$DOJO_URL" DOJO_SSH_HOST="$CONTAINER_IP" pytest --order-dependencies -v test
