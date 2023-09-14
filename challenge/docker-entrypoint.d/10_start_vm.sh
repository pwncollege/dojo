#!/bin/sh

if ! find /challenge -name '*.ko' -exec false {} +
then
  vm start
else
  chmod -s "$(which vm)"
fi

if [[ -f /challenge/challenge.exe ]]; then
  windows start
else
  chmod -s "$(which windows)"
fi
