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

VOLUME_ARGS=("-v" "$PWD:/opt/pwn.college" "-v" "$PWD/data:/data:shared")
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
			VOLUME_ARGS[3]="$DATA_DIR:/data:shared"
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
	"-v" "/data/dojos"
	"-v" "/data/mysql"
)

export CONTAINER_NAME
docker kill "$CONTAINER_NAME" 2>/dev/null || echo "No $CONTAINER_NAME container to kill."
docker rm "$CONTAINER_NAME" 2>/dev/null || echo "No $CONTAINER_NAME container to remove."
while docker ps -a | grep "$CONTAINER_NAME"; do sleep 1; done

# freaking bad unmount
sleep 1
mount | grep $PWD | sed -e "s/.* on //" | sed -e "s/ .*//" | tac | while read ENTRY
do
	sudo umount "$ENTRY"
done

docker run --rm --privileged -d "${VOLUME_ARGS[@]}" "${ENV_ARGS[@]}" -p 2222:22 -p 80:80 -p 443:443 --name "$CONTAINER_NAME" dojo || exit 1

# fix the insane routing thing
read -a GW <<<$(ip route show default)
read -a NS <<<$(docker exec "$CONTAINER_NAME" cat /etc/resolv.conf | grep nameserver)
docker exec "$CONTAINER_NAME" ip route add "${GW[2]}" via 172.17.0.1
docker exec "$CONTAINER_NAME" ip route add "${NS[1]}" via 172.17.0.1 || echo "Failed to add nameserver route"

docker exec "$CONTAINER_NAME" dojo wait
if [ -n "$DB_RESTORE" ]
then
	BASENAME=$(basename $DB_RESTORE)
	docker exec "$CONTAINER_NAME" mkdir -p /data/backups/
	[ -f "$DB_RESTORE" ] && docker cp "$DB_RESTORE" "$CONTAINER_NAME":/data/backups/"$BASENAME"
	docker exec "$CONTAINER_NAME" dojo restore "$BASENAME"
fi

until curl -Ls localhost.pwn.college | grep -q pwn; do sleep 1; done
# fix up the data permissions and git
sudo chown "$USER:$USER" "$PWD/data"
git checkout "$PWD/data/.gitkeep" || true

[ "$TEST" == "yes" ] && MOZ_HEADLESS=1 pytest -v test/test_running.py test/test_welcome.py
