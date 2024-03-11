#!/bin/sh

chown hacker:hacker /home/hacker
chmod 755 /home/hacker

if [ -x "/challenge/.init" ]; then
    /challenge/.init
fi
