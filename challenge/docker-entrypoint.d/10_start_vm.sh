#!/bin/sh

find /challenge -name '*.ko' -exec false {} + || vm start
