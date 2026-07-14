#!/usr/bin/env bash
# railway_start.sh
#
# Arranque "inteligente" para Railway.
# - Si el servicio define la variable CRON_COMMAND  -> corre ese management command y termina.
#     (lo usan los servicios de cron: renovaciones, reporte de bajas, etc.)
# - Si NO la define                                 -> arranca el servidor web (gunicorn).
#     (lo usa el servicio web de siempre)
#
# Así un solo repo + un solo railway.toml sirve para el web y para todos los crons.

set -e

if [ -n "$CRON_COMMAND" ]; then
  echo "🕒 Modo cron → python3 manage.py $CRON_COMMAND"
  python3 manage.py $CRON_COMMAND
else
  echo "🌐 Modo web → migraciones + estáticos + gunicorn"
  python3 manage.py migrate
  python3 manage.py collectstatic --noinput

  # 👤 Crea el superusuario si DJANGO_SUPERUSER_* está seteado en Railway.
  # Si el usuario ya existe, createsuperuser falla solo (no pisa la contraseña
  # existente) — por eso el "|| true": no rompe deploys siguientes.
  if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "👤 Creando superusuario (si no existe todavía)..."
    python3 manage.py createsuperuser --noinput || true
  fi

  exec gunicorn seguros_project.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 2 --threads 4 \
    --timeout 60 --keep-alive 5 \
    --max-requests 1000 --max-requests-jitter 50
fi