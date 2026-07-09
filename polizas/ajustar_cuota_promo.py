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

  # ─────────────────────────────────────────────────────────────
  # 🏷️ TEMPORAL — PROMO ROJAS (AA870GR → cuotas impagas a $25.000)
  #    1) Deploy así (SIMULACIÓN): mirá los logs.
  #    2) Si está OK → comentá la simulación y descomentá la de --aplicar.
  #    3) Redeploy: aplica.
  #    ⚠️  BORRAR ESTE BLOQUE después del deploy exitoso.
  # ─────────────────────────────────────────────────────────────
  python3 manage.py ajustar_cuota_promo --patente AA870GR --monto 25000
  # python3 manage.py ajustar_cuota_promo --patente AA870GR --monto 25000 --aplicar
  # ─────────────────────────────────────────────────────────────

  exec gunicorn seguros_project.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 2 --threads 4 \
    --timeout 60 --keep-alive 5 \
    --max-requests 1000 --max-requests-jitter 50
fi