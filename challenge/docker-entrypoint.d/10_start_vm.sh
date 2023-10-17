#!/bin/sh

if ! find /challenge -name '*.ko' -exec false {} +
then
  vm start
fi

if ! find /challenge -name '*.exe' -exec false {} +
then
  windows start
fi
