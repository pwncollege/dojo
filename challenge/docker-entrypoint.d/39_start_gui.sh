#!/bin/sh

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
seq 1 50 | while read cnt; do sleep 0.1; [ -e /tmp/.X11-unix/X42 ] && break; done
DISPLAY=:42 xfce4-session &
