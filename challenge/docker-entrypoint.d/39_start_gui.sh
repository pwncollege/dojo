#!/bin/sh

mkdir -p /tmp/.dojo/vnc /home/hacker/.vnc

echo "$(head -c32 /dev/urandom | md5sum | head -c8)" > /home/hacker/.vnc/pass-interact
echo "$(head -c32 /dev/urandom | md5sum | head -c8)" > /home/hacker/.vnc/pass-view
cat /home/hacker/.vnc/pass-interact /home/hacker/.vnc/pass-view | tigervncpasswd -f > /home/hacker/.vnc/vncpass

start-stop-daemon --start \
                  --pidfile /tmp/.dojo/vnc/vncserver.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/Xtigervnc \
                  -- \
                  :42 \
                  -localhost=0 \
                  -rfbunixpath /tmp/.dojo/vnc/vnc_socket \
                  -rfbauth /home/hacker/.vnc/vncpass \
                  -nolisten tcp \
                  -geometry 1024x768 \
                  -depth 24 \
                  </dev/null \
                  >>/tmp/.dojo/vnc/vncserver.log \
                  2>&1

start-stop-daemon --start \
                  --pidfile /tmp/.dojo/vnc/websockify.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/websockify \
                  -- \
                  --web /usr/share/novnc/ \
                  dojo-user:6081 \
                  --unix-target=/tmp/.dojo/vnc/vnc_socket \
                  </dev/null \
                  >>/tmp/.dojo/vnc/websockify.log \
                  2>&1

seq 1 50 | while read cnt; do sleep 0.1; [ -e /tmp/.X11-unix/X42 ] && break; done

export DISPLAY=:42

if [ -e /home/hacker/.xinitrc ]
then
	/bin/sh /home/hacker/.xinitrc
elif [ -x /usr/bin/xfce4-session ]
then
	xfce4-session &
else
	fluxbox &
fi
