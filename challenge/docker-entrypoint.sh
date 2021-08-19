#!/bin/sh

nohup code-server --auth=none --socket=/home/hacker/.local/share/code-server/workspace.socket --extensions-dir=/opt/code-server/extensions --disable-telemetry > /tmp/code-server.log &

exec /bin/sleep 6h
