#!/bin/bash

if [ "${DB_EXTERNAL:-no}" = "no" ]
then
    /docker-entrypoint.sh mysqld --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci --wait_timeout=28800 --log-warnings=0
else
    while true; do sleep 86400; done
fi
