#!/bin/bash

PROMPT_COMMAND="history -a"

mkdir -p /tmp/.dojo

if [ -e "/challenge/README.md" ] && [ ! -e "/tmp/.dojo/readme-once" ]; then
    if command -v glow > /dev/null 2>&1; then
        PAGER="less -ERX" glow --pager /challenge/README.md
    elif command -v less > /dev/null 2>&1; then
        less -ERX /challenge/README.md
    else
	cat /challenge/README.md
    fi

    touch /tmp/.dojo/readme-once
fi

[ -f "/challenge/.bashrc" ] && source /challenge/.bashrc
