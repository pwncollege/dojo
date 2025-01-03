#!/bin/bash -ex

cd $(dirname "${BASH_SOURCE[0]}")/..

function usage {
	set +x
	echo "Usage: $0 [-r DB_BACKUP ] [ -c DOJO_CONTAINER ] [ -D DOCKER_DIR ] [ -T ]"
	echo ""
	echo "	-r	full path to db backup to restore"
	echo "	-c	the name of the dojo container (default: dojo-test)"
	echo "	-D	specify a directory for /data/docker (to avoid rebuilds)"
	echo "	-T	don't run tests"
	exit
}

WORKDIR=$(mktemp -d /tmp/dojo-test-XXXXXX)

VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$WORKDIR:/data:shared")
ENV_ARGS=( )
DB_RESTORE=""
DOJO_CONTAINER=dojo-test
TEST=yes
DOCKER_DIR=""
while getopts "r:c:he:TD:" OPT
do
	case $OPT in
		r) DB_RESTORE="$OPTARG" ;;
		c) DOJO_CONTAINER="$OPTARG" ;;
		T) TEST=no ;;
		D) DOCKER_DIR="$OPTARG" ;;
		e) ENV_ARGS+=("-e" "$OPTARG") ;;
		h) usage ;;
		?)
			OPTIND=$(($OPTIND-1))
			break
			;;
	esac
done
shift $((OPTIND-1))

export DOJO_CONTAINER
docker kill "$DOJO_CONTAINER" 2>/dev/null || echo "No $DOJO_CONTAINER container to kill."
docker rm "$DOJO_CONTAINER" 2>/dev/null || echo "No $DOJO_CONTAINER container to remove."
while docker ps -a | grep "$DOJO_CONTAINER"; do sleep 1; done

# freaking bad unmount
sleep 1
mount | grep /tmp/dojo-test- | sed -e "s/.* on //" | sed -e "s/ .*//" | tac | while read ENTRY
do
	sudo umount "$ENTRY"
done

if [ -n "$DOCKER_DIR" ]
then
	VOLUME_ARGS+=( "-v" "$DOCKER_DIR:/data/docker" )
	sudo rm -rf $DOCKER_DIR/{containers,volumes}
fi

docker run --rm --privileged -d "${VOLUME_ARGS[@]}" "${ENV_ARGS[@]}" -p 2222:22 -p 80:80 -p 443:443 --name "$DOJO_CONTAINER" dojo || exit 1

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

until curl -Ls localhost.pwn.college | grep -q pwn; do sleep 1; done

docker exec "$DOJO_CONTAINER" docker pull pwncollege/challenge-simple
docker exec "$DOJO_CONTAINER" docker tag pwncollege/challenge-simple pwncollege/challenge-legacy

[ "$TEST" == "yes" ] && MOZ_HEADLESS=1 pytest -v test/test_running.py test/test_welcome.py
