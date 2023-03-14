#!/bin/sh -x

DIR="$(readlink -f $(dirname $_))"

mkdir -p "$DIR"/data
touch "$DIR"/data/config.env

if [ "$1" = "init" ]; then
    > "$DIR"/data/.config.env

    define () {
        name="$1"
        default="$2"
        re="^${name}=\K.*"
        current="$(env | grep -oP ${re})"
        defined="$(grep -oP ${re} $DIR/data/config.env)"
        value="${current:-${defined:-$default}}"
        echo "${name}=${value}" >> $DIR/data/.config.env
    }

    define DOJO_HOST localhost.pwn.college
    define DOJO_SSH_PORT 22
    define DOJO_HTTP_PORT 80
    define DOJO_HTTPS_PORT 443

    define SECRET_KEY $(openssl rand -hex 16)
    define DOCKER_PSLR $(openssl rand -hex 16)

    define DISCORD_CLIENT_ID
    define DISCORD_CLIENT_SECRET
    define DISCORD_BOT_TOKEN
    define DISCORD_GUILD_ID

    mv "$DIR"/data/.config.env "$DIR"/data/config.env

    cat "$DIR"/data/config.env
fi

. "$DIR"/data/config.env

ACTION="$1"
shift

DOCKER_INPUT_MODE="-it"
[ -t 0 ] || DOCKER_INPUT_MODE="-i"

if [ "$ACTION" = "build" ]; then
    docker build -t "$DOJO_HOST" .

elif [ "$ACTION" = "run" ]; then
    $0 build
    $0 stop

    docker run \
           --privileged \
           --detach \
           --rm \
           --volume "$DIR"/data/docker:/var/lib/docker \
           --volume "$DIR"/data:/opt/pwn.college/data \
           --volume "$DIR"/dojo_plugin:/opt/CTFd/CTFd/plugins/dojo_plugin:ro \
           --volume "$DIR"/dojo_theme:/opt/CTFd/CTFd/themes/dojo_theme:ro \
           --volume "$DIR"/discord_bot:/opt/pwn.college/discord_bot:ro \
           --volume "$DIR"/challenge:/opt/pwn.college/challenge:ro \
           --publish "$DOJO_SSH_PORT":22 \
           --publish "$DOJO_HTTP_PORT":80 \
           --publish "$DOJO_HTTPS_PORT":443 \
           --hostname "$DOJO_HOST" \
           --name "$DOJO_HOST" \
           "$DOJO_HOST"

    docker logs -f "$DOJO_HOST"

elif [ "$ACTION" = "stop" ]; then
    while [ $(docker ps -a -q -f name="$DOJO_HOST") ]; do
        docker kill "$DOJO_HOST" || sleep 1
    done

elif [ "$ACTION" = "restart" ]; then
    $0 stop
    $0 run

elif [ "$ACTION" = "docker" ]; then
    docker exec $DOCKER_INPUT_MODE "$DOJO_HOST" docker "$@"

elif [ "$ACTION" = "sh" ]; then
    docker exec $DOCKER_INPUT_MODE "$DOJO_HOST" bash "$@"

elif [ "$ACTION" = "logs" ]; then
    $0 docker compose --env-file=/opt/pwn.college/data/config.env  logs -f

elif [ "$ACTION" = "db" ]; then
	$0 docker exec $DOCKER_INPUT_MODE ctfd_db mysql -u ctfd --password=ctfd ctfd "$@"

elif [ "$ACTION" = "manage" ]; then
	$0 docker exec $DOCKER_INPUT_MODE ctfd python manage.py "$@"

elif [ "$ACTION" = "update" ]; then
    git -C "$DIR" pull
    git -C "$DIR"/data/dojos pull

    $0 docker compose --env-file=/opt/pwn.college/data/config.env build
    $0 docker compose --env-file=/opt/pwn.college/data/config.env kill ctfd
    $0 docker compose --env-file=/opt/pwn.college/data/config.env rm -f ctfd
    $0 docker compose --env-file=/opt/pwn.college/data/config.env up -d ctfd

elif [ "$ACTION" = "backup" ]; then
    $0 docker kill ctfd
    cp -a "$DIR"/data/mysql "$DIR"/data/mysql.bak-$(date -Iminutes)
    $0 docker start ctfd
fi
