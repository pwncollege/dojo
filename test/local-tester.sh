#!/bin/bash -exu

cd $(dirname "${BASH_SOURCE[0]}")/..

REPO_DIR=$(basename "$PWD")
DEFAULT_CONTAINER_NAME="local-${REPO_DIR}"

function usage {
	set +x
	echo "Usage: $0 [-r DB_BACKUP ] [ -c DOJO_CONTAINER ] [ -D DOCKER_DIR ] [ -W WORKSPACE_DIR ] [ -T ] [ -p ] [ -e ENV_VAR=value ] [ -b ] [ -M ] [ -g ]"
	echo ""
	echo "	-r	full path to db backup to restore"
	echo "	-c	the name of the dojo container (default: local-<dirname>)"
	echo "	-D	specify a directory for /data/docker (to avoid rebuilds)"
	echo "	-W	specify a directory for /data/workspace (to avoid rebuilds)"
	echo "	-T	don't run tests"
	echo "	-p	export ports (80->80, 443->443, 22->2222)"
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
	sleep 4
	mount | grep /tmp/local-data-${CONTAINER}-....../ | sed -e "s/.* on //" | sed -e "s/ .*//" | tac | while read ENTRY
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
TEST=yes
DOCKER_DIR=""
WORKSPACE_DIR=""
EXPORT_PORTS=no
BUILD_IMAGE=no
MULTINODE=no
GITHUB_ACTIONS=no
while getopts "r:c:he:TD:W:pbMg" OPT
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
		M) MULTINODE=yes ;;
		g) GITHUB_ACTIONS=yes ;;
		h) usage ;;
		?)
			OPTIND=$(($OPTIND-1))
			break
			;;
	esac
done
shift $((OPTIND-1))

export DOJO_CONTAINER

cleanup_container $DOJO_CONTAINER
if [ "$MULTINODE" == "yes" ]; then
	cleanup_container $DOJO_CONTAINER-node1
	cleanup_container $DOJO_CONTAINER-node2
fi

WORKDIR=$(mktemp -d /tmp/local-data-${DOJO_CONTAINER}-XXXXXX)
if [ "$MULTINODE" == "yes" ]; then
	WORKDIR_NODE1=$(mktemp -d /tmp/local-data-${DOJO_CONTAINER}-node1-XXXXXX)
	WORKDIR_NODE2=$(mktemp -d /tmp/local-data-${DOJO_CONTAINER}-node2-XXXXXX)
fi

MAIN_NODE_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$WORKDIR:/data:shared")
[ -n "$WORKSPACE_DIR" ] && MAIN_NODE_VOLUME_ARGS+=( "-v" "$WORKSPACE_DIR:/data/workspace:shared" )
if [ -n "$DOCKER_DIR" ]; then
	MAIN_NODE_VOLUME_ARGS+=( "-v" "$DOCKER_DIR:/data/docker" )
	sudo rm -rf $DOCKER_DIR/{containers,volumes}
fi

if [ "$MULTINODE" == "yes" ]; then
	NODE1_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$WORKDIR_NODE1:/data:shared")
	NODE2_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$WORKDIR_NODE2:/data:shared")
	[ -n "$WORKSPACE_DIR" ] && NODE1_VOLUME_ARGS+=("-v" "$WORKSPACE_DIR:/data/workspace:shared")
	[ -n "$WORKSPACE_DIR" ] && NODE2_VOLUME_ARGS+=("-v" "$WORKSPACE_DIR:/data/workspace:shared")
	if [ -n "$DOCKER_DIR" ]; then
		NODE1_VOLUME_ARGS+=("-v" "$DOCKER_DIR-node1:/data/docker")
		NODE2_VOLUME_ARGS+=("-v" "$DOCKER_DIR-node2:/data/docker")
		sudo rm -rf $DOCKER_DIR-node1/{containers,volumes}
		sudo rm -rf $DOCKER_DIR-node2/{containers,volumes}
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
docker run --rm --privileged -d "${MAIN_NODE_VOLUME_ARGS[@]}" "${ENV_ARGS[@]}" "${PORT_ARGS[@]}" "${MULTINODE_ARGS[@]}" --name "$DOJO_CONTAINER" "$IMAGE_NAME" || exit 1
CONTAINER_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$DOJO_CONTAINER")
fix_insane_routing "$DOJO_CONTAINER"

docker exec "$DOJO_CONTAINER" dojo wait
docker exec "$DOJO_CONTAINER" docker pull pwncollege/challenge-simple
docker exec "$DOJO_CONTAINER" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy
log_endgroup

if [ "$MULTINODE" == "yes" ]; then
	log_newgroup "Setting up multi-node cluster"
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

	docker exec "$DOJO_CONTAINER-node1" docker pull pwncollege/challenge-simple
	docker exec "$DOJO_CONTAINER-node1" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy
	docker exec "$DOJO_CONTAINER-node2" docker pull pwncollege/challenge-simple
	docker exec "$DOJO_CONTAINER-node2" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy

	# this is needed for the main node to understand that it's in multi-node mode
	docker exec "$DOJO_CONTAINER" dojo up
	docker exec "$DOJO_CONTAINER-node1" dojo up
	docker exec "$DOJO_CONTAINER-node2" dojo up
	
	# Fix routing for user containers on workspace nodes
	log_newgroup "Configuring multi-node networking"
	
	# Enable IP forwarding on all nodes
	docker exec "$DOJO_CONTAINER" sysctl -w net.ipv4.ip_forward=1
	docker exec "$DOJO_CONTAINER-node1" sysctl -w net.ipv4.ip_forward=1
	docker exec "$DOJO_CONTAINER-node2" sysctl -w net.ipv4.ip_forward=1
	
	# Fix routes on main node to match production (direct to wg0, not via specific IP)
	docker exec "$DOJO_CONTAINER" bash -c "ip route del 10.16.0.0/12 2>/dev/null || true"
	docker exec "$DOJO_CONTAINER" bash -c "ip route del 10.32.0.0/12 2>/dev/null || true"
	docker exec "$DOJO_CONTAINER" ip route add 10.16.0.0/12 dev wg0
	docker exec "$DOJO_CONTAINER" ip route add 10.32.0.0/12 dev wg0
	
	# Add the critical MASQUERADE rule from production for the entire 10.0.0.0/8 network
	docker exec "$DOJO_CONTAINER" bash -c "iptables -t nat -C POSTROUTING -s 10.0.0.0/8 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s 10.0.0.0/8 -j MASQUERADE"
	
	# Wait a moment for routes to settle
	sleep 10
	
	log_endgroup
fi

if [ -n "$DB_RESTORE" ]
then
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
	pytest --order-dependencies -v test "$@"
	log_endgroup
fi
