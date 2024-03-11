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

AVAILABLE_M="$(df --block-size=1M --output=avail /home/hacker | tail -n +2 | head -n1)"
if [[ "$AVAILABLE_M" -lt 512 ]]; then
    echo 'Note: Your home directory is running low on storage:'
    df -h /home/hacker
    echo ''
    echo 'Filling your home directory completely could cause you to lose access to the workspace and/or desktop.'
    echo 'You can view a list of the largest files and directories using the command:'
    echo '  du -sh /home/hacker/* | sort -h'
fi

[ -f "/challenge/.bashrc" ] && source /challenge/.bashrc
