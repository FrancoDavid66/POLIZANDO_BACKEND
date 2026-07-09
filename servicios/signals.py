# servicios/signals.py
# 🚀 Mantiene "en espejo" las categorías de Servicios y las de Balances (egresos),
#    para que ingresos manuales, egresos manuales y servicios fijos compartan
#    una sola lista de categorías.
#
#    Reglas:
#    - Solo sincroniza ALTAS (crear / renombrar). NO borra nada.
#    - Las categorías de servicio se reflejan como EGRESO en Balances.
#    - Las de Balances se reflejan a Servicios solo si son EGRESO o AMBOS
#      (las de tipo INGRESO no van a servicios).
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CategoriaServicio, ServicioFijo
from balanzes.models import Categoria


def _existe(qs_model, nombre):
    return qs_model.objects.filter(nombre__iexact=nombre).exists()


@receiver(post_save, sender=CategoriaServicio)
def categoria_servicio_a_balanzes(sender, instance, **kwargs):
    """Categoría de servicio nueva -> aparece en Balances como EGRESO."""
    nombre = (instance.nombre or "").strip()
    if not nombre:
        return
    if not _existe(Categoria, nombre):
        Categoria.objects.create(nombre=nombre, tipo="EGRESO")


@receiver(post_save, sender=Categoria)
def categoria_balanzes_a_servicios(sender, instance, **kwargs):
    """Categoría de Balances (EGRESO/AMBOS) -> aparece en la lista de Servicios."""
    tipo = (instance.tipo or "").upper()
    if tipo not in ("EGRESO", "AMBOS"):
        return
    nombre = (instance.nombre or "").strip()
    if not nombre:
        return
    if not _existe(CategoriaServicio, nombre):
        CategoriaServicio.objects.create(nombre=nombre)


@receiver(post_save, sender=ServicioFijo)
def categoria_de_servicio_fijo(sender, instance, **kwargs):
    """Si un servicio fijo usa una categoría suelta, la registramos en ambas listas."""
    nombre = (instance.categoria or "").strip()
    if not nombre:
        return
    if not _existe(Categoria, nombre):
        Categoria.objects.create(nombre=nombre, tipo="EGRESO")
    if not _existe(CategoriaServicio, nombre):
        CategoriaServicio.objects.create(nombre=nombre)