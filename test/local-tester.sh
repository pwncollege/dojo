#!/bin/bash

cd $(dirname "${BASH_SOURCE[0]}")/..
args=()
run_tests=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        -T)
            run_tests=false
            shift
            ;;
        *)
            args+=("$1")
            shift
            ;;
    esac
done

if $run_tests; then
    args+=("-t")
fi

exec ./deploy.sh "${args[@]}"
