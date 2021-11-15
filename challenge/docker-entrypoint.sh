#!/bin/sh

mkdir /tmp/code-server
start-stop-daemon --start \
                  --pidfile /tmp/code-server/code-server.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/code-server \
                  -- \
                  --auth=none \
                  --socket=/home/hacker/.local/share/code-server/workspace.socket \
                  --extensions-dir=/opt/code-server/extensions \
                  --disable-telemetry \
                  </dev/null \
                  >>/tmp/code-server/code-server.log \
                  2>&1

find /challenge -name '*.ko' -exec false {} + || vm start

exec /bin/sleep 6h
