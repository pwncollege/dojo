#!/bin/sh
set -eu
cd /opt/pwn.college
python -m dojo_plugin.bootstrap
case "${DOJO_ENV:-}" in
  development)
    export FLASK_DEBUG=True WERKZEUG_DEBUG_PIN=off
    exec flask run --host 0.0.0.0 --port 8000 ;;
  coverage)
    export FLASK_DEBUG=True WERKZEUG_DEBUG_PIN=off
    exec coverage run --source=dojo_plugin -m flask run --no-reload --host 0.0.0.0 --port 8000 ;;
  production)
    exec gunicorn 'dojo_plugin:create_app()' --bind 0.0.0.0:8000 --workers "${WORKERS:-8}" \
      --worker-tmp-dir /dev/shm --worker-class gevent --access-logfile - --error-logfile - ;;
  *)
    echo "Failed to start ctfd - environment variable DOJO_ENV has invalid value \"${DOJO_ENV:-}\"" >&2
    exit 1 ;;
esac
