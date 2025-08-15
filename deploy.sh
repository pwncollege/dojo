#!/bin/bash -exu

cd $(dirname "${BASH_SOURCE[0]}")

REPO_DIR=$(basename "$PWD")
DEFAULT_CONTAINER_NAME="${REPO_DIR}"

function usage {
	set +x
	echo "Usage: $0 [-r DB_BACKUP ] [ -c DOJO_CONTAINER ] [ -D DOCKER_DIR ] [ -W WORKSPACE_DIR ] [ -t ] [ -N ] [ -p ] [ -e ENV_VAR=value ] [ -b ] [ -M ] [ -g ]"
	echo ""
	echo "	-r	full path to db backup to restore"
	echo "	-c	the name of the dojo container (default: <dirname>)"
	echo "	-D	specify a directory for /data/docker to avoid rebuilds (default: ./cache/docker; specify as blank to disable)"
	echo "	-W	specify a directory for /data/workspace to avoid rebuilds (default: ./cache/workspace; specify as blank to disable)"
	echo "	-t	run dojo testcases (this will create a lot of test data)"
	echo "	-N	don't (re)start the dojo"
	echo "	-P	export ports (80->80, 443->443, 22->2222)"
	echo "	-e	set environment variable (can be used multiple times)"
	echo "	-b	build the Docker image locally (tag: same as container name)"
	echo "	-M	run in multi-node mode (3 containers: 1 main + 2 workspace nodes)"
	echo "	-g	use GitHub Actions group output formatting"
	exit
}


function cleanup_container {
	local CONTAINER=$1
	docker kill "$CONTAINER" 2>/dev/null || echo "No $CONTAINER container to kill."
	docker rm "$CONTAINER" 2>/dev/null || echo "No $CONTAINER container to remove."
	while docker ps -a | grep "$CONTAINER$"; do sleep 1; done

	# freaking bad unmount
	mount | grep /tmp/data-${CONTAINER}-....../ && sleep 4
	mount | grep /tmp/data-${CONTAINER}-....../ | sed -e "s/.* on //" | sed -e "s/ .*//" | tac | while read ENTRY
	do
		sudo umount "$ENTRY" || echo "Failed ^"
	done
}

function fix_insane_routing {
	local CONTAINER="$1"
	read -a GW <<<$(ip route show default)
	read -a NS <<<$(docker exec "$CONTAINER" cat /etc/resolv.conf | grep nameserver)
	docker exec "$CONTAINER" ip route add "${GW[2]}" via 172.17.0.1
	[ "${GW[2]}" == "${NS[1]}" ] || docker exec "$CONTAINER" ip route add "${NS[1]}" via 172.17.0.1
}

function log_newgroup {
	local title="$1"
	if [ "$GITHUB_ACTIONS" == "yes" ]; then
		echo "::group::$title"
	else
		echo "=== $title ==="
	fi
}

function log_endgroup {
	if [ "$GITHUB_ACTIONS" == "yes" ]; then
		echo "::endgroup::"
	fi
}

ENV_ARGS=( )
DB_RESTORE=""
DOJO_CONTAINER="$DEFAULT_CONTAINER_NAME"
TEST=no
DOCKER_DIR="./cache/docker"
WORKSPACE_DIR="./cache/workspace"
EXPORT_PORTS=no
BUILD_IMAGE=no
MULTINODE=no
GITHUB_ACTIONS=no
START=yes
while getopts "r:c:he:tD:W:PbMgN" OPT
do
	case $OPT in
		r) DB_RESTORE="$OPTARG" ;;
		c) DOJO_CONTAINER="$OPTARG" ;;
		t) TEST=yes ;;
		D) DOCKER_DIR="$OPTARG" ;;
		W) WORKSPACE_DIR="$OPTARG" ;;
		e) ENV_ARGS+=("-e" "$OPTARG") ;;
		p) EXPORT_PORTS=yes ;;
		b) BUILD_IMAGE=yes ;;
		M) MULTINODE=yes ;;
		g) GITHUB_ACTIONS=yes ;;
		N) START=no ;;
		h) usage ;;
		?)
			OPTIND=$(($OPTIND-1))
			break
			;;
	esac
done
shift $((OPTIND-1))

export DOJO_CONTAINER

if [ "$START" == "yes" ]; then
	cleanup_container $DOJO_CONTAINER

	# just in case a previous run was multinode...
	cleanup_container $DOJO_CONTAINER-node1
	cleanup_container $DOJO_CONTAINER-node2
fi

WORKDIR=$(mktemp -d /tmp/data-${DOJO_CONTAINER}-XXXXXX)
if [ "$MULTINODE" == "yes" ]; then
	WORKDIR_NODE1=$(mktemp -d /tmp/data-${DOJO_CONTAINER}-node1-XXXXXX)
	WORKDIR_NODE2=$(mktemp -d /tmp/data-${DOJO_CONTAINER}-node2-XXXXXX)
fi

MAIN_NODE_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$WORKDIR:/data:shared")
[ -n "$WORKSPACE_DIR" ] && MAIN_NODE_VOLUME_ARGS+=( "-v" "$WORKSPACE_DIR:/data/workspace:shared" )
if [ -n "$DOCKER_DIR" ]; then
	MAIN_NODE_VOLUME_ARGS+=( "-v" "$DOCKER_DIR:/data/docker" )
	if [ "$START" == "yes" ]; then
		sudo rm -rf $DOCKER_DIR/{containers,volumes}
	fi
fi

if [ "$MULTINODE" == "yes" ]; then
	NODE1_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$WORKDIR_NODE1:/data:shared")
	NODE2_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$WORKDIR_NODE2:/data:shared")
	[ -n "$WORKSPACE_DIR" ] && NODE1_VOLUME_ARGS+=("-v" "$WORKSPACE_DIR:/data/workspace:shared")
	[ -n "$WORKSPACE_DIR" ] && NODE2_VOLUME_ARGS+=("-v" "$WORKSPACE_DIR:/data/workspace:shared")
	if [ -n "$DOCKER_DIR" ]; then
		NODE1_VOLUME_ARGS+=("-v" "$DOCKER_DIR-node1:/data/docker")
		NODE2_VOLUME_ARGS+=("-v" "$DOCKER_DIR-node2:/data/docker")
		if [ "$START" == "yes" ]; then
			sudo rm -rf $DOCKER_DIR-node1/{containers,volumes}
			sudo rm -rf $DOCKER_DIR-node2/{containers,volumes}
		fi
	fi
fi

IMAGE_NAME="pwncollege/dojo"
if [ "$BUILD_IMAGE" == "yes" ]; then
	log_newgroup "Building Docker image with tag: $DOJO_CONTAINER"
	docker build -t "$DOJO_CONTAINER" . || exit 1
	IMAGE_NAME="$DOJO_CONTAINER"
	log_endgroup
fi

PORT_ARGS=()
if [ "$EXPORT_PORTS" == "yes" ]; then
	PORT_ARGS+=("-p" "80:80" "-p" "443:443" "-p" "2222:22")
fi

MULTINODE_ARGS=()
[ "$MULTINODE" == "yes" ] && MULTINODE_ARGS+=("-e" "WORKSPACE_NODE=0")

log_newgroup "Starting main dojo container"
if [ "$START" == "yes" ]; then
	docker run --rm --privileged -d \
		"${MAIN_NODE_VOLUME_ARGS[@]}" "${ENV_ARGS[@]}" "${PORT_ARGS[@]}" "${MULTINODE_ARGS[@]}" \
		--name "$DOJO_CONTAINER" "$IMAGE_NAME" \
		|| exit 1
fi
CONTAINER_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$DOJO_CONTAINER")
if [ "$START" == "yes" ]; then
	fix_insane_routing "$DOJO_CONTAINER"
	docker exec "$DOJO_CONTAINER" dojo wait

	if [ "$MULTINODE" == "no" ]; then
		docker exec "$DOJO_CONTAINER" docker wait workspace-builder
		docker exec "$DOJO_CONTAINER" docker pull pwncollege/challenge-simple
		docker exec "$DOJO_CONTAINER" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy
	fi
fi

log_endgroup

if [ "$START" == "yes" -a "$MULTINODE" == "yes" ]; then
	log_newgroup "Setting up multi-node cluster"

	# Disconnect nginx-proxy from workspace_net for multinode routing to work
	docker exec "$DOJO_CONTAINER" docker network disconnect workspace_net nginx-proxy 2>/dev/null || true

	docker exec "$DOJO_CONTAINER" dojo-node refresh
	MAIN_KEY=$(docker exec "$DOJO_CONTAINER" cat /data/wireguard/publickey)

	docker run --rm --privileged -d \
		"${NODE1_VOLUME_ARGS[@]}" \
		"${ENV_ARGS[@]}" \
		-e WORKSPACE_NODE=1 \
		-e WORKSPACE_KEY="$MAIN_KEY" \
		-e DOJO_HOST="$CONTAINER_IP" \
		-e STORAGE_HOST="$CONTAINER_IP" \
		--name "$DOJO_CONTAINER-node1" \
		"$IMAGE_NAME"
	fix_insane_routing "$DOJO_CONTAINER-node1"

	docker run --rm --privileged -d \
		"${NODE2_VOLUME_ARGS[@]}" \
		"${ENV_ARGS[@]}" \
		-e WORKSPACE_NODE=2 \
		-e WORKSPACE_KEY="$MAIN_KEY" \
		-e DOJO_HOST="$CONTAINER_IP" \
		-e STORAGE_HOST="$CONTAINER_IP" \
		--name "$DOJO_CONTAINER-node2" \
		"$IMAGE_NAME"
	fix_insane_routing "$DOJO_CONTAINER-node2"

	# Wait for workspace containers and set up WireGuard
	docker exec "$DOJO_CONTAINER-node1" dojo wait
	docker exec "$DOJO_CONTAINER-node2" dojo wait

	docker exec "$DOJO_CONTAINER-node1" dojo-node refresh
	docker exec "$DOJO_CONTAINER-node2" dojo-node refresh

	# Register workspace nodes with main node
	NODE1_KEY=$(docker exec "$DOJO_CONTAINER-node1" cat /data/wireguard/publickey)
	NODE2_KEY=$(docker exec "$DOJO_CONTAINER-node2" cat /data/wireguard/publickey)

	docker exec "$DOJO_CONTAINER" dojo-node add 1 "$NODE1_KEY"
	docker exec "$DOJO_CONTAINER" dojo-node add 2 "$NODE2_KEY"
	sleep 5
	docker exec "$DOJO_CONTAINER" dojo compose restart ctfd sshd
	sleep 5
	docker exec "$DOJO_CONTAINER" dojo wait

	docker exec "$DOJO_CONTAINER-node1" docker wait workspace-builder
	docker exec "$DOJO_CONTAINER-node1" docker pull pwncollege/challenge-simple
	docker exec "$DOJO_CONTAINER-node1" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy
	docker exec "$DOJO_CONTAINER-node2" docker wait workspace-builder
	docker exec "$DOJO_CONTAINER-node2" docker pull pwncollege/challenge-simple
	docker exec "$DOJO_CONTAINER-node2" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy

	log_endgroup
fi

if [ -n "$DB_RESTORE" ]; then
	log_newgroup "Restoring database backup"
	BASENAME=$(basename $DB_RESTORE)
	docker exec "$DOJO_CONTAINER" mkdir -p /data/backups/
	[ -f "$DB_RESTORE" ] && docker cp "$DB_RESTORE" "$DOJO_CONTAINER":/data/backups/"$BASENAME"
	docker exec "$DOJO_CONTAINER" dojo restore "$BASENAME"
	log_endgroup
fi

log_newgroup "Waiting for dojo to be ready"
export DOJO_URL="http://${CONTAINER_IP}"
export DOJO_SSH_HOST="$CONTAINER_IP"
until curl -Ls "${DOJO_URL}" | grep -q pwn; do sleep 1; done
log_endgroup

if [ "$TEST" == "yes" ]; then
	log_newgroup "Running tests"
	export MOZ_HEADLESS=1
	pytest --order-dependencies --timeout=60 -v test "$@"
	log_endgroup
fi
