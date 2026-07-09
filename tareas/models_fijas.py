# tareas/models_fijas.py
#
# Módulo "Tareas fijas": tareas operativas RECURRENTES que el personal debe
# hacer (abrir, cerrar, sacar carteles, limpiar...) y que se verifican subiendo
# una FOTO como prueba. Distintas de las "tareas del día" (que salen solas de
# las pólizas). Estas las define el admin a mano.
#
# Para que Django las detecte, agregá al final de tareas/models.py:
#     from .models_fijas import TareaFija, CumplimientoTareaFija, Feriado

from django.conf import settings
from django.db import models


class TareaFija(models.Model):
    """Definición de una tarea recurrente (la 'plantilla')."""

    FRECUENCIA = (
        ("diaria", "Todos los días"),
        ("semanal", "Ciertos días de la semana"),
    )

    nombre = models.CharField(max_length=120, help_text="Ej: Abrir la oficina, Sacar los carteles")

    # Oficina dueña de la tarea. Si queda vacío, la tarea aplica a TODAS las oficinas.
    oficina = models.ForeignKey(
        "usuarios.Oficina",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tareas_fijas",
        help_text="Vacío = aplica a todas las oficinas.",
    )

    # Responsable: quién tiene que hacerla (para el buchón / control).
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tareas_fijas_a_cargo",
    )

    frecuencia = models.CharField(max_length=10, choices=FRECUENCIA, default="diaria")

    # Para frecuencia semanal: días de la semana como CSV de enteros (lunes=0 ... domingo=6).
    # Ej: "0,2,4" = lunes, miércoles y viernes. Vacío en frecuencia diaria.
    dias_semana = models.CharField(max_length=20, blank=True, default="")

    # Horario esperado (para las alertas a horario de la Parte 2). Opcional.
    hora_esperada = models.TimeField(null=True, blank=True, help_text="Ej: 09:00. Vacío = sin alerta de horario.")
    margen_alerta = models.PositiveIntegerField(default=15, help_text="Minutos de tolerancia tras la hora antes de alertar y restar puntos.")
    premia_demora = models.BooleanField(default=False, help_text="Tareas de cierre: cerrar más tarde suma puntos (horas extra) en vez de restar.")

    requiere_foto = models.BooleanField(default=True)
    instruccion_foto = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Qué tiene que mostrar la foto. Ej: la cortina abierta.",
    )
    # 🆕 Cantidad de fotos: mínimo para quedar cumplida y máximo permitido.
    fotos_min = models.PositiveIntegerField(default=1, help_text="Fotos mínimas para que la tarea quede cumplida (verde).")
    fotos_max = models.PositiveIntegerField(default=1, help_text="Fotos máximas que se pueden subir. Debe ser >= fotos_min.")
    activa = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0, help_text="Orden de aparición en la lista.")

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tarea fija"
        verbose_name_plural = "Tareas fijas"
        ordering = ["orden", "nombre"]

    def __str__(self):
        ofi = self.oficina.nombre if self.oficina else "Todas"
        return f"{self.nombre} ({ofi})"

    def dias_lista(self):
        """Devuelve la lista de días (ints) para frecuencia semanal."""
        if not self.dias_semana:
            return []
        out = []
        for x in str(self.dias_semana).split(","):
            x = x.strip()
            if x.isdigit():
                out.append(int(x))
        return out

    def aplica_en(self, fecha):
        """¿Esta tarea corresponde hacerse en `fecha`?"""
        if not self.activa:
            return False
        if self.frecuencia == "diaria":
            return True
        if self.frecuencia == "semanal":
            return fecha.weekday() in self.dias_lista()
        return False


class CumplimientoTareaFija(models.Model):
    """Registro de que una tarea fija se cumplió (con su foto) en una fecha/oficina."""

    tarea = models.ForeignKey(
        TareaFija, on_delete=models.CASCADE, related_name="cumplimientos"
    )
    # Oficina donde se cumplió (importante para tareas globales que cada oficina cumple).
    oficina = models.ForeignKey(
        "usuarios.Oficina",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cumplimientos_tareas_fijas",
    )
    fecha = models.DateField()

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cumplimientos_tareas_fijas",
    )

    # 🆕 Responsable real que hizo la tarea (el empleado elegido en los chips).
    #    Distinto de `usuario` (la cuenta que subió la foto).
    responsable_empleado = models.ForeignKey(
        "solicitudes.Empleado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cumplimientos_tareas_fijas",
    )
    # Nombre del responsable congelado (por si el empleado se borra después).
    responsable_nombre = models.CharField(max_length=120, blank=True, default="")
    # True si lo cargó un admin en nombre del responsable (no la persona misma).
    cargado_por_admin = models.BooleanField(default=False)

    foto_url = models.URLField(max_length=600, blank=True, default="")
    foto_public_id = models.CharField(max_length=255, blank=True, default="")

    # adelantado / a_tiempo / tarde / sin_hora
    estado_tiempo = models.CharField(max_length=12, blank=True, default="")
    puntos = models.IntegerField(default=0)

    cumplido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cumplimiento de tarea fija"
        verbose_name_plural = "Cumplimientos de tareas fijas"
        ordering = ["-cumplido_en"]
        # Una tarea se cumple una sola vez por oficina por día.
        unique_together = ("tarea", "oficina", "fecha")

    def __str__(self):
        return f"{self.tarea.nombre} · {self.fecha}"


class Feriado(models.Model):
    """Días en los que NO se esperan tareas fijas (no cuentan como incumplidas)."""

    fecha = models.DateField(unique=True)
    nombre = models.CharField(max_length=120, help_text="Ej: 9 de Julio")
    nacional = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Feriado"
        verbose_name_plural = "Feriados"
        ordering = ["fecha"]

    def __str__(self):
        return f"{self.fecha} · {self.nombre}"


class FotoCumplimiento(models.Model):
    """Cada foto subida para un cumplimiento de tarea (varias por tarea)."""
    cumplimiento = models.ForeignKey(
        CumplimientoTareaFija, on_delete=models.CASCADE, related_name="fotos"
    )
    foto_url = models.URLField(max_length=600)
    foto_public_id = models.CharField(max_length=255, blank=True, default="")
    # Quién la subió (la cuenta) y el responsable real de la tarea.
    responsable_nombre = models.CharField(max_length=120, blank=True, default="")
    cargado_por_admin = models.BooleanField(default=False)
    subida_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Foto de cumplimiento"
        verbose_name_plural = "Fotos de cumplimiento"
        ordering = ["subida_en"]

    def __str__(self):
        return f"Foto de {self.cumplimiento_id}"


class AlertaTareaFijaEnviada(models.Model):
    """
    Marca que ya se envió la alerta de "no cumplida a horario" para una
    tarea/oficina/día, así no se repite el aviso cada vez que corre el cron.
    """
    tarea = models.ForeignKey(TareaFija, on_delete=models.CASCADE, related_name="alertas")
    oficina = models.ForeignKey(
        "usuarios.Oficina", on_delete=models.CASCADE, null=True, blank=True,
        related_name="alertas_tareas_fijas",
    )
    fecha = models.DateField()
    enviada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Alerta de tarea fija enviada"
        verbose_name_plural = "Alertas de tareas fijas enviadas"
        unique_together = ("tarea", "oficina", "fecha")

    def __str__(self):
        return f"Alerta {self.tarea.nombre} · {self.fecha}"