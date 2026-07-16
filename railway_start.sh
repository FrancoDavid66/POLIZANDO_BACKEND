#!/usr/bin/env bash
# railway_start.sh

set -e

if [ -n "$CRON_COMMAND" ]; then
  echo "🕒 Modo cron → python3 manage.py $CRON_COMMAND"
  python3 manage.py $CRON_COMMAND
else
  echo "🌐 Modo web → migraciones + estáticos + gunicorn"
  python3 manage.py migrate
  python3 manage.py collectstatic --noinput

  exec gunicorn seguros_project.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 2 --threads 4 \
    --timeout 60 --keep-alive 5 \
    --max-requests 1000 --max-requests-jitter 50
fi