#!/bin/sh

ps aux | grep -q code-serve[r] && exit

mkdir -p /tmp/.dojo/code-server
start-stop-daemon --start \
                  --pidfile /tmp/.dojo/code-server/code-server.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/code-server \
                  -- \
                  --auth=none \
                  --bind-addr=dojo-user:6080 \
                  --extensions-dir=/opt/code-server/extensions \
                  --disable-telemetry \
                  </dev/null \
                  >>/tmp/.dojo/code-server/code-server.log \
                  2>&1

until curl -s dojo-user:6080 >/dev/null; do sleep 0.1; done
