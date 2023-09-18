
if [[ -f /challenge/challenge.exe ]]; then
  start-stop-daemon --start \
                    --pidfile /tmp/vnc/websockify-windows.pid \
                    --make-pidfile \
                    --background \
                    --no-close \
                    --startas /usr/bin/websockify \
                    -- \
                    --web /usr/share/novnc/ \
                    24153 \
                    localhost:5912 \
                    </dev/null \
                    >>/tmp/vnc/websockify-windows.log \
                    2>&1

  rm -f /home/hacker/.vnc/novnc-windows.socket
  start-stop-daemon --start \
                    --pidfile /tmp/vnc/socat-windows.pid \
                    --make-pidfile \
                    --background \
                    --no-close \
                    --startas /usr/bin/socat \
                    -- \
                    UNIX-LISTEN:/home/hacker/.vnc/novnc-windows.socket,fork \
                    TCP-CONNECT:localhost:24153 \
                    </dev/null \
                    >>/tmp/vnc/socat-windows.log \
                    2>&1
fi
