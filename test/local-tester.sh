#!/bin/bash -ex

cd $(dirname "${BASH_SOURCE[0]}")/..

function usage {
	set +x
	echo "Usage: $0 [-r DB_BACKUP ] [ -c CONTAINER_NAME ] [ -T ]"
	echo ""
	echo "	-r	db backup to restore (relative to dojo/data/backups)"
	echo "	-c	the name of the dojo container (default: dojo-test)"
	echo "	-D	use a blank data volume (builds everything from scratch)"
	echo "	-T	don't run tests"
	exit
}

VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college:shared")
ENV_ARGS=( )
DB_RESTORE=""
CONTAINER_NAME=dojo-test
TEST=yes
while getopts "r:c:he:TD" OPT
do
	case $OPT in
		r) DB_RESTORE="$OPTARG" ;;
		c) CONTAINER_NAME="$OPTARG" ;;
		T) TEST=no ;;
		D)
			DATA_DIR=$(mktemp -d)
			VOLUME_ARGS+=("-v" "$DATA_DIR:/opt/pwn.college/data:shared")
			;;
		e) ENV_ARGS+=("-e" "$OPTARG") ;;
		h) usage ;;
		?)
			OPTIND=$(($OPTIND-1))
			break
			;;
	esac
done
shift $((OPTIND-1))

[ "${#VOLUME_ARGS[@]}" -eq 2 ] && VOLUME_ARGS+=(
	"-v" "/opt/pwn.college/data/dojos"
	"-v" "/opt/pwn.college/data/mysql"
)

export CONTAINER_NAME
docker kill "$CONTAINER_NAME" 2>/dev/null || echo "No $CONTAINER_NAME container to kill."
docker rm "$CONTAINER_NAME" 2>/dev/null || echo "No $CONTAINER_NAME container to remove."
while docker ps -a | grep "$CONTAINER_NAME"; do sleep 1; done

# freaking bad unmount
sleep 1
mount | grep $PWD | while read -a ENTRY
do
	sudo umount "${ENTRY[2]}"
done

docker run --rm --privileged -d "${VOLUME_ARGS[@]}" "${ENV_ARGS[@]}" -p 2222:22 -p 80:80 -p 443:443 --name "$CONTAINER_NAME" dojo || exit 1

# fix the insane routing thing
read -a GW <<<$(ip route show default)
read -a NS <<<$(docker exec "$CONTAINER_NAME" cat /etc/resolv.conf | grep nameserver)
docker exec "$CONTAINER_NAME" ip route add "${GW[2]}" via 172.17.0.1
docker exec "$CONTAINER_NAME" ip route add "${NS[1]}" via 172.17.0.1 || echo "Failed to add nameserver route"

docker exec "$CONTAINER_NAME" dojo wait
[ -n "$DB_RESTORE" ] && until docker exec "$CONTAINER_NAME" dojo restore $DB_RESTORE; do sleep 1; done

until curl -s localhost.pwn.college | grep -q pwn; do sleep 1; done
[ "$TEST" == "yes" ] && MOZ_HEADLESS=1 pytest -v test/test_running.py test/test_welcome.py
