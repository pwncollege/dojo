#!/bin/sh

if ! find /challenge -name '*.ko' -exec false {} +
then
  vm start
else
  chmod -s "$(which vm)"
fi

if ! find /challenge -name '*.exe' -exec false {} +
then
  windows start
else
  chmod -s "$(which windows)"
fi
