#!/bin/bash

mkdir -p /tmp/.dojo

if [ -e "/challenge/README.md" ] && [ ! -e "/tmp/.dojo/readme-once" ]; then
    if command -v glow > /dev/null 2>&1; then
        PAGER="less -ERX" glow --pager /challenge/README.md
    else
        less -ERX /challenge/README.md
    fi

    touch /tmp/.dojo/readme-once
fi

[ -f "/challenge/.bashrc" ] && source /challenge/.bashrc
