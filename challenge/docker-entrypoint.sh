#!/bin/sh

find /challenge -name '*.ko' -exec false {} + || vm start

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

mkdir -p /tmp/vnc /home/hacker/.vnc
echo "$(head -c32 /dev/urandom | md5sum | head -c8)" > /home/hacker/.vnc/pass-interact
echo "$(head -c32 /dev/urandom | md5sum | head -c8)" > /home/hacker/.vnc/pass-view
cat /home/hacker/.vnc/pass-interact /home/hacker/.vnc/pass-view | tigervncpasswd -f > /home/hacker/.vnc/vncpass
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
                  -rfbauth /home/hacker/.vnc/vncpass \
                  -nolisten tcp \
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
seq 1 50 | while read; do sleep 0.1; [ -e /tmp/.X11-unix/X42 ] && break; done
mkdir -p /home/hacker/.config/gtk-3.0
[ -f /home/hacker/.config/gtk-3.0/bookmarks ] || echo "file:///challenge" > /home/hacker/.config/gtk-3.0/bookmarks
[ -f /home/hacker/QtProject.conf ] || cat <<END > /home/hacker/.config/QtProject.conf
[FileDialog]
history=file:///home/hacker
lastVisited=file:///
qtVersion=5.15.2
shortcuts=file:, file:///home/hacker, file:///challenge
sidebarWidth=90
treeViewHeader=@ByteArray(\0\0\0\xff\0\0\0\0\0\0\0\x1\0\0\0\0\0\0\0\0\x1\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\x1\xec\0\0\0\x4\x1\x1\0\0\0\0\0\0\0\0\0\0\0\0\0\0\x64\xff\xff\xff\xff\0\0\0\x81\0\0\0\0\0\0\0\x4\0\0\0\xff\0\0\0\x1\0\0\0\0\0\0\0?\0\0\0\x1\0\0\0\0\0\0\0@\0\0\0\x1\0\0\0\0\0\0\0n\0\0\0\x1\0\0\0\0\0\0\x3\xe8\0\xff\xff\xff\xff)
viewMode=List
END
[ ! -d /home/hacker/.config/xfce4 ] && cp -r /usr/share/desktop-base/profiles/xdg-config/xfce4 /home/hacker/.config/xfce4
DISPLAY=:42 xfce4-session &
