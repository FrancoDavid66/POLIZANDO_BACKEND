# Agregar este método a la clase EnviarRecordatoriosCuotasView
# en notificaciones/views.py
# 
# También agregar esta URL en notificaciones/urls.py:
# path("cuotas/enviar-todas-oficinas/", EnviarTodasOficinasView.as_view(), name="enviar-todas-oficinas"),

import threading
import time

class EnviarTodasOficinasView(APIView):
    """
    POST /api/notificaciones/cuotas/enviar-todas-oficinas/

    Lanza el envío de recordatorios para TODAS las oficinas en secuencia.
    Cuando termina una oficina, espera 5 minutos y arranca la siguiente.

    Body:
      - alias / alias_transferencia
      - medio_cobro_id
      - pausa_entre_oficinas: segundos entre cada oficina (default: 300 = 5 min)

    Siempre es async (responde inmediato, el proceso corre en background).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Solo admin puede enviar a todas las oficinas
        user = request.user
        es_admin = user.is_superuser or (hasattr(user, "perfil") and user.perfil.rol == "ADMIN")
        if not es_admin:
            return Response(
                {"ok": False, "error": "Solo el administrador puede enviar a todas las oficinas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        alias          = request.data.get("alias") or request.data.get("alias_transferencia")
        medio_cobro_id = _parse_int(request.data.get("medio_cobro_id"))
        pausa          = int(request.data.get("pausa_entre_oficinas", 300))  # 5 min default
        job_id         = str(uuid.uuid4())

        # Obtener todas las oficinas activas
        try:
            from usuarios.models import Oficina
            oficinas = list(
                Oficina.objects.filter(activo=True).values_list("id", flat=True)
            )
        except Exception:
            oficinas = ["1", "2", "3", "4"]  # fallback

        oficinas_str = [str(o) for o in oficinas]

        def _runner_todas():
            hoy = timezone.localdate()
            print(f"[EnviarTodas] Iniciando envío para {len(oficinas_str)} oficinas: {oficinas_str}")

            for idx, ofi in enumerate(oficinas_str):
                print(f"[EnviarTodas] ▶ Oficina {ofi} ({idx+1}/{len(oficinas_str)})")
                try:
                    enviar_recordatorios_cuotas(
                        hoy=hoy,
                        alias_transferencia=alias or None,
                        medio_cobro_id=medio_cobro_id,
                        oficina=ofi,
                    )
                    print(f"[EnviarTodas] ✅ Oficina {ofi} — envío completado")
                except Exception as exc:
                    print(f"[EnviarTodas] ❌ Oficina {ofi} — error: {exc}")

                # Pausa entre oficinas (excepto después de la última)
                if idx < len(oficinas_str) - 1:
                    print(f"[EnviarTodas] ⏸ Pausa de {pausa}s antes de la siguiente oficina...")
                    time.sleep(pausa)

            print(f"[EnviarTodas] 🏁 Todas las oficinas completadas.")

        th = threading.Thread(target=_runner_todas, daemon=True)
        th.start()

        return Response(
            {
                "ok":      True,
                "async":   True,
                "job_id":  job_id,
                "oficinas": oficinas_str,
                "pausa_entre_oficinas": pausa,
                "nota": (
                    f"Envío iniciado para {len(oficinas_str)} oficinas. "
                    f"Se procesarán en secuencia con {pausa}s de pausa entre cada una."
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )