# ranking/models.py
#
# "Monedero" central de puntos: cada acción de la oficina que sume (o reste)
# puntos a un empleado crea un MovimientoPuntos. El ranking junta todo.

from django.conf import settings
from django.db import models


class MovimientoPuntos(models.Model):
    """Un registro de puntos ganados (o perdidos) por un empleado."""

    CATEGORIAS = (
        ("control_diario", "Control diario"),
        ("tarea_dia", "Tarea del día"),
        ("venta", "Venta / alta"),
        ("renovacion", "Renovación"),
        ("pago", "Cobro / pago"),
        ("otro", "Otro"),
    )

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="movimientos_puntos",
    )
    oficina = models.ForeignKey(
        "usuarios.Oficina",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="movimientos_puntos",
    )
    fecha = models.DateField()
    puntos = models.IntegerField(help_text="Positivo suma, negativo resta.")
    categoria = models.CharField(max_length=20, choices=CATEGORIAS, default="otro")
    detalle = models.CharField(max_length=200, blank=True, default="")

    # Referencia única opcional para no duplicar puntos por la misma acción.
    # Ej: "control_diario:123" (id del cumplimiento). Vacío = no se controla.
    ref = models.CharField(max_length=80, blank=True, default="", db_index=True)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Movimiento de puntos"
        verbose_name_plural = "Movimientos de puntos"
        ordering = ["-creado_en"]
        indexes = [models.Index(fields=["fecha"]), models.Index(fields=["usuario", "fecha"])]

    def __str__(self):
        signo = "+" if self.puntos >= 0 else ""
        return f"{self.usuario} {signo}{self.puntos} ({self.categoria})"