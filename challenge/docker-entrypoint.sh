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

# vnc
mkdir -p /tmp/vnc
start-stop-daemon --start \
                  --pidfile /tmp/vnc/vncserver.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/Xtigervnc \
                  -- \
                  :42 \
                  -localhost=0 \
                  -rfbunixpath /tmp/vnc/vnc_socket \
                  -nolisten tcp \
                  -SecurityTypes None \
                  -geometry 1024x768 \
                  -depth 24 \
                  </dev/null \
                  >>/tmp/vnc/vncserver.log \
                  2>&1
start-stop-daemon --start \
                  --pidfile /tmp/vnc/websockify.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/websockify \
                  -- \
                  --web /usr/share/novnc/ \
                  24152 \
                  --unix-target=/tmp/vnc/vnc_socket \
                  </dev/null \
                  >>/tmp/vnc/websockify.log \
                  2>&1
mkdir -p /home/hacker/.vnc
rm -f /home/hacker/.vnc/novnc.socket
start-stop-daemon --start \
                  --pidfile /tmp/vnc/socat.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/socat \
                  -- \
                  UNIX-LISTEN:/home/hacker/.vnc/novnc.socket,fork \
                  TCP-CONNECT:localhost:24152 \
                  </dev/null \
                  >>/tmp/vnc/socat.log \
                  2>&1
sleep 1
mkdir -p /home/hacker/.config
[ ! -d /home/hacker/.config/xfce4 ] && cp -r /usr/share/desktop-base/profiles/xdg-config/xfce4 /home/hacker/.config/xfce4
DISPLAY=:42 xfce4-session &

find /challenge -name '*.ko' -exec false {} + || vm start

exec /bin/sleep 6h
