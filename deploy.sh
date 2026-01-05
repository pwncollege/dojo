#!/bin/bash -eu

cd $(dirname "${BASH_SOURCE[0]}")

REPO_DIR=$(basename "$PWD")
DEFAULT_CONTAINER_NAME="${REPO_DIR}"

function usage {
	set +x
	echo "Usage: $0 [-r DB_BACKUP ] [ -c DOJO_CONTAINER ] [ -D DOCKER_DIR ] [ -W WORKSPACE_DIR ] [ -t ] [ -v ] [ -N ] [ -p ] [ -e ENV_VAR=value ] [ -b ] [ -M ] [ -g ] [ -C ]"
	echo ""
	echo "	-r	full path to db backup to restore"
	echo "	-c	the name of the dojo container (default: <dirname>)"
	echo "	-D	specify a directory for /data/docker to avoid rebuilds (default: ./cache/docker; specify as blank to disable)"
	echo "	-W	specify a directory for /data/workspace to avoid rebuilds (default: ./cache/workspace; specify as blank to disable)"
	echo "	-t	run dojo testcases (this will create a lot of test data)"
	echo "	-v	run vibecheck mode (summarize git diff and test with AI)"
	echo "	-N	don't (re)start the dojo"
	echo "	-K	clean up and exit"
	echo "	-P	export ports (80->80, 443->443, 22->2222)"
	echo "	-e	set environment variable (can be used multiple times)"
	echo "	-b	build the Docker image locally (tag: same as container name)"
	echo "	-M	run in multi-node mode (3 containers: 1 main + 2 workspace nodes)"
	echo "	-g	use GitHub Actions group output formatting"
	echo "	-C	run the ctfd container with code coverage. Generates an xml coverage report when paired with the -t flag"
	exit
}


function cleanup_container {
	local CONTAINER=$1
	docker kill "$CONTAINER" 2>/dev/null || echo "No $CONTAINER container to kill."
	docker rm "$CONTAINER" 2>/dev/null || echo "No $CONTAINER container to remove."
	while docker ps -a | grep "$CONTAINER$"; do sleep 1; done
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

TEST_CONTAINER_EXTRA_ARGS=()

function test_container {
        local args=(
                --rm
                -v /var/run/docker.sock:/var/run/docker.sock
                -v "$PWD:/opt/pwn.college"
                --name "${DOJO_CONTAINER}-test"
                -e "OPENAI_API_KEY=${OPENAI_API_KEY:-}"
        )

        args+=("${TEST_CONTAINER_EXTRA_ARGS[@]}")

        docker run "${args[@]}" "${DOJO_CONTAINER}-test" "$@"
}

function generate_coverage_report {
	local CONTAINER="$1"
    docker exec "$CONTAINER" docker kill -s SIGINT ctfd
	docker exec "$CONTAINER" docker wait ctfd
    docker exec "$CONTAINER" docker start ctfd
    docker exec "$CONTAINER" docker exec ctfd coverage xml -o /var/coverage/coverage.xml
}

ENV_ARGS=( )
DB_RESTORE=""
DOJO_CONTAINER="$DEFAULT_CONTAINER_NAME"
TEST=no
VIBECHECK=no
DOCKER_DIR="./cache/docker"
WORKSPACE_DIR="./cache/workspace"
EXPORT_PORTS=no
BUILD_IMAGE=no
MULTINODE=no
GITHUB_ACTIONS=no
CLEAN_ONLY=no
START=yes
COVERAGE=no
while getopts "r:c:he:tvD:W:PbMgNKC" OPT
do
	case $OPT in
		r) DB_RESTORE="$OPTARG" ;;
		c) DOJO_CONTAINER="$OPTARG" ;;
		t) TEST=yes ;;
		v) VIBECHECK=yes ;;
		D) DOCKER_DIR="$OPTARG" ;;
		W) WORKSPACE_DIR="$OPTARG" ;;
		e) ENV_ARGS+=("-e" "$OPTARG") ;;
		p) EXPORT_PORTS=yes ;;
		b) BUILD_IMAGE=yes ;;
		M) MULTINODE=yes ;;
		g) GITHUB_ACTIONS=yes ;;
		N) START=no ;;
		K) CLEAN_ONLY=yes ;;
		C) COVERAGE=yes ;;
		h) usage ;;
		?)
			OPTIND=$(($OPTIND-1))
			break
			;;
	esac
done
shift $((OPTIND-1))

if [ "$START" == "yes" -o "$CLEAN_ONLY" == "yes" ]; then
	cleanup_container $DOJO_CONTAINER
	cleanup_container $DOJO_CONTAINER-test

	# just in case a previous run was multinode...
	cleanup_container $DOJO_CONTAINER-node1
	cleanup_container $DOJO_CONTAINER-node2
fi

if [ "$CLEAN_ONLY" == "yes" ]; then
	exit
fi

MAIN_NODE_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college")
[ -n "$WORKSPACE_DIR" ] && MAIN_NODE_VOLUME_ARGS+=( "-v" "$WORKSPACE_DIR:/data/workspace:shared" )
if [ -n "$DOCKER_DIR" ]; then
	MAIN_NODE_VOLUME_ARGS+=( "-v" "$DOCKER_DIR:/data/docker" )
	if [ "$START" == "yes" ]; then
		sudo rm -rf $DOCKER_DIR/{containers,volumes}
	fi
fi

if [ "$MULTINODE" == "yes" ]; then
	NODE1_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college")
	NODE2_VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college")
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
	log_newgroup "Building test container $DOJO_CONTAINER-test"
	docker build -t "${DOJO_CONTAINER}-test" test/
	log_endgroup
elif ! docker image inspect "${DOJO_CONTAINER}-test" >&/dev/null
then
	log_newgroup "Building test container $DOJO_CONTAINER-test (it doesn't exist)"
	docker build -t "${DOJO_CONTAINER}-test" test/
	log_endgroup
fi

PORT_ARGS=()
if [ "$EXPORT_PORTS" == "yes" ]; then
	PORT_ARGS+=("-p" "80:80" "-p" "443:443" "-p" "2222:22")
fi

MULTINODE_ARGS=()
if [ "$MULTINODE" == "yes" ]; then
	if [ -z "${WORKSPACE_SECRET:-}" ]; then
		WORKSPACE_SECRET=$(openssl rand -hex 16)
	fi
	MULTINODE_ARGS+=("-e" "WORKSPACE_NODE=0")
	ENV_ARGS+=("-e" "WORKSPACE_SECRET=$WORKSPACE_SECRET")
fi

if [ "$COVERAGE" == "yes" ]; then
	ENV_ARGS+=("-e" "DOJO_ENV=coverage")
fi

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
		if ! docker exec "$DOJO_CONTAINER" docker ps -a | grep workspace-builder | grep "Exited (0)"
		then
			docker exec "$DOJO_CONTAINER" docker logs workspace-builder | tail -n100
			echo "WORKSPACE BUILDER FAILED"
			exit 1
		fi
		docker exec "$DOJO_CONTAINER" docker pull pwncollege/challenge-simple
		docker exec "$DOJO_CONTAINER" docker pull pwncollege/challenge-lecture
		docker exec "$DOJO_CONTAINER" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy
	fi
fi

log_endgroup

DOJO_HOST_CONFIG=$(docker exec "$DOJO_CONTAINER" sh -c 'echo -n "${DOJO_HOST-}"')
WORKSPACE_HOST_CONFIG=$(docker exec "$DOJO_CONTAINER" sh -c 'echo -n "${WORKSPACE_HOST-}"')

if [ -z "$DOJO_HOST_CONFIG" ]; then
        DOJO_HOST_CONFIG="localhost.pwn.college"
fi

if [ -z "$WORKSPACE_HOST_CONFIG" ]; then
        WORKSPACE_HOST_CONFIG="workspace.${DOJO_HOST_CONFIG}"
fi

if [[ "$DOJO_HOST_CONFIG" != "$CONTAINER_IP" && "$DOJO_HOST_CONFIG" =~ [A-Za-z] ]]; then
        TEST_CONTAINER_EXTRA_ARGS+=("--add-host" "${DOJO_HOST_CONFIG}:${CONTAINER_IP}")
fi

if [[ "$WORKSPACE_HOST_CONFIG" != "$CONTAINER_IP" && "$WORKSPACE_HOST_CONFIG" != "$DOJO_HOST_CONFIG" && "$WORKSPACE_HOST_CONFIG" =~ [A-Za-z] ]]; then
        TEST_CONTAINER_EXTRA_ARGS+=("--add-host" "${WORKSPACE_HOST_CONFIG}:${CONTAINER_IP}")
fi

if [ "$START" == "yes" -a "$MULTINODE" == "yes" ]; then
	log_newgroup "Setting up multi-node cluster"

	# Disconnect nginx from workspace_net for multinode routing to work
	docker exec "$DOJO_CONTAINER" docker network disconnect workspace_net nginx 2>/dev/null || true

	docker exec "$DOJO_CONTAINER" dojo-node refresh
	MAIN_KEY=$(docker exec "$DOJO_CONTAINER" cat /data/wireguard/publickey)

	docker run --rm --privileged -d \
		"${NODE1_VOLUME_ARGS[@]}" \
		"${ENV_ARGS[@]}" \
		-e WORKSPACE_NODE=1 \
		-e WORKSPACE_KEY="$MAIN_KEY" \
		-e DOJO_HOST="$CONTAINER_IP" \
		-e STORAGE_HOST="$CONTAINER_IP" \
		-e "WORKSPACE_HOST=node-1.workspace.${DOJO_HOST_CONFIG}" \
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
		-e "WORKSPACE_HOST=node-2.workspace.${DOJO_HOST_CONFIG}" \
		--name "$DOJO_CONTAINER-node2" \
		"$IMAGE_NAME"
	fix_insane_routing "$DOJO_CONTAINER-node2"

	# Wait for workspace containers and set up WireGuard
	docker exec "$DOJO_CONTAINER-node1" dojo wait
	docker exec "$DOJO_CONTAINER-node2" dojo wait

	NODE1_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$DOJO_CONTAINER-node1")
	NODE2_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$DOJO_CONTAINER-node2")

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
	docker exec "$DOJO_CONTAINER" dojo compose restart nginx
	sleep 5
	docker exec "$DOJO_CONTAINER" dojo wait

	docker exec "$DOJO_CONTAINER-node1" docker wait workspace-builder
	docker exec "$DOJO_CONTAINER-node1" docker pull pwncollege/challenge-simple
	docker exec "$DOJO_CONTAINER-node1" docker pull pwncollege/challenge-lecture
	docker exec "$DOJO_CONTAINER-node1" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy
	docker exec "$DOJO_CONTAINER-node2" docker wait workspace-builder
	docker exec "$DOJO_CONTAINER-node2" docker pull pwncollege/challenge-simple
	docker exec "$DOJO_CONTAINER-node2" docker pull pwncollege/challenge-lecture
	docker exec "$DOJO_CONTAINER-node2" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy

	log_endgroup
fi

if [ "$MULTINODE" == "yes" ]; then
        for NODE in 1 2; do
                NODE_CONTAINER="$DOJO_CONTAINER-node${NODE}"
                if docker inspect "$NODE_CONTAINER" >/dev/null 2>&1; then
                        NODE_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NODE_CONTAINER")
                        if [ -n "$NODE_IP" ]; then
                                TEST_CONTAINER_EXTRA_ARGS+=("--add-host" "node-${NODE}.workspace.${DOJO_HOST_CONFIG}:${NODE_IP}")
                        fi
                fi
        done
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
until curl -Ls "http://${CONTAINER_IP}" | grep -q pwn; do sleep 1; done
log_endgroup

if [ "$TEST" == "yes" ]; then
	log_newgroup "Running tests in container"
	cleanup_container $DOJO_CONTAINER-test
	test_container pytest --order-dependencies --timeout=60 -v . "$@"
	if [ "$COVERAGE" == "yes" ]; then
		generate_coverage_report "$DOJO_CONTAINER"
	fi
	log_endgroup
fi

if [ "$VIBECHECK" == "yes" ]; then
	log_newgroup "Preparing vibe check"

	if [ -z "${OPENAI_API_KEY:-}" ]; then
		echo "::warning title=openai key not set::skipping vibe check"
		exit 0
	fi

	git diff $(git merge-base --fork-point origin/master HEAD) > test/git_diff.txt
	test_container npx --yes @openai/codex exec \
		--full-auto --skip-git-repo-check \
		'Summarize the following git diff in a concise way, focusing on what functionality has changed and what areas of the application might be affected. The + lines are things added in this PR, the - lines are things deleted by this PR. Be specific about files and components modified. The raw diff is saved in git_diff.txt. Save your analysis in the file `diff_summary`.'
	log_endgroup

	test_container python3 vibe_check.py
fi
