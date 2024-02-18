#!/bin/sh

mkdir -p /tmp/.dojo/vnc /home/hacker/.vnc
start-stop-daemon --start \
                  --pidfile /tmp/.dojo/vnc/websockify-windows.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/websockify \
                  -- \
                  --web /usr/share/novnc/ \
                  dojo-user:6082 \
                  localhost:5912 \
                  </dev/null \
                  >>/tmp/.dojo/vnc/websockify-windows.log \
                  2>&1
