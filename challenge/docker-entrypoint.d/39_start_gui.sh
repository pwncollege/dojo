#!/bin/sh

mkdir -p /tmp/.dojo/vnc /home/hacker/.vnc

container_id="$(cat /proc/1/cgroup | tail -n 1 | awk -F '/' '{print $NF}')"
password_interact="$(printf 'desktop-interact' | openssl dgst -sha256 -hmac "$container_id" | awk '{print $2}' | head -c 8)"
password_view="$(printf 'desktop-view' | openssl dgst -sha256 -hmac "$container_id" | awk '{print $2}' | head -c 8)"
printf '%s\n%s\n' "$password_interact" "$password_view" | tigervncpasswd -f > /tmp/.dojo/vnc/passwd

start-stop-daemon --start \
                  --pidfile /tmp/.dojo/vnc/vncserver.pid \
                  --make-pidfile \
                  --background \
                  --no-close \
                  --startas /usr/bin/Xtigervnc \
                  -- \
                  :42 \
                  -localhost=0 \
                  -rfbunixpath /tmp/.dojo/vnc/socket \
                  -rfbauth /tmp/.dojo/vnc/passwd \
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
                  --unix-target=/tmp/.dojo/vnc/socket \
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
