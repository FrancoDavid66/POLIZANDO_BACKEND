from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver

from historia.models import PolizaEvento
from historia.utils import create_event

# --- Import base de modelos polizas ---
from polizas.models import Poliza, PolizaDocumento, FotoVehiculo

# ---- Documentos ----
@receiver(post_save, sender=PolizaDocumento)
def doc_creado(sender, instance: PolizaDocumento, created, **kwargs):
    if created:
        create_event(
            poliza=instance.poliza,
            categoria=PolizaEvento.Categoria.DOC,
            tipo=PolizaEvento.Tipo.DOC_SUBIR,
            severidad="INFO",
            mensaje=f"Subido {instance.tipo}",
            data={
                "documento_id": instance.id,
                "tipo": instance.tipo,
                "nombre": instance.nombre,
                "mime": instance.mime,
                "vencimiento": instance.vencimiento.isoformat() if instance.vencimiento else None,
                "url": instance.url,
                "public_id": instance.public_id,
            },
            subject=instance,
            source="SYSTEM",
        )

@receiver(pre_save, sender=PolizaDocumento)
def doc_cambio_vto(sender, instance: PolizaDocumento, **kwargs):
    if not instance.pk:
        return
    try:
        old = PolizaDocumento.objects.get(pk=instance.pk)
    except PolizaDocumento.DoesNotExist:
        return
    if old.vencimiento != instance.vencimiento:
        create_event(
            poliza=instance.poliza,
            categoria=PolizaEvento.Categoria.DOC,
            tipo=PolizaEvento.Tipo.DOC_CAMBIAR_VTO,
            severidad="ACTION",
            mensaje=f"Cambio de vencimiento en {instance.tipo}",
            data={
                "documento_id": instance.pk,
                "tipo": instance.tipo,
                "antes": old.vencimiento.isoformat() if old.vencimiento else None,
                "despues": instance.vencimiento.isoformat() if instance.vencimiento else None,
                "nombre": instance.nombre,
            },
            subject=instance,
            source="SYSTEM",
        )

@receiver(post_delete, sender=PolizaDocumento)
def doc_borrado(sender, instance: PolizaDocumento, **kwargs):
    create_event(
        poliza=instance.poliza,
        categoria=PolizaEvento.Categoria.DOC,
        tipo=PolizaEvento.Tipo.DOC_BORRAR,
        severidad="WARNING",
        mensaje=f"Eliminado {instance.tipo}",
        data={
            "documento_id": instance.id,
            "tipo": instance.tipo,
            "nombre": instance.nombre,
            "url": instance.url,
            "public_id": instance.public_id,
        },
        subject=instance,
        source="SYSTEM",
    )

# ---- Fotos ----
@receiver(post_save, sender=FotoVehiculo)
def foto_creada(sender, instance: FotoVehiculo, created, **kwargs):
    if created:
        create_event(
            poliza=instance.poliza,
            categoria=PolizaEvento.Categoria.FOTO,
            tipo=PolizaEvento.Tipo.FOTO_SUBIR,
            severidad="INFO",
            mensaje=f"Subida foto {instance.tipo}",
            data={
                "foto_id": instance.id,
                "tipo": instance.tipo,
                "origen": instance.origen,
                "url": instance.url,
                "public_id": instance.public_id,
            },
            subject=instance,
            source="SYSTEM",
        )

@receiver(post_delete, sender=FotoVehiculo)
def foto_borrada(sender, instance: FotoVehiculo, **kwargs):
    create_event(
        poliza=instance.poliza,
        categoria=PolizaEvento.Categoria.FOTO,
        tipo=PolizaEvento.Tipo.FOTO_BORRAR,
        severidad="WARNING",
        mensaje=f"Eliminada foto {instance.tipo}",
        data={
            "foto_id": instance.id,
            "tipo": instance.tipo,
            "origen": instance.origen,
            "url": instance.url,
            "public_id": instance.public_id,
        },
        subject=instance,
        source="SYSTEM",
    )

# ---- Foto de perfil en Poliza (detecta cambios) ----
@receiver(pre_save, sender=Poliza)
def poliza_cambio_foto_perfil(sender, instance: Poliza, **kwargs):
    if not instance.pk:
        return
    try:
        old = Poliza.objects.get(pk=instance.pk)
    except Poliza.DoesNotExist:
        return
    if old.foto_perfil_url != instance.foto_perfil_url:
        create_event(
            poliza=instance,
            categoria=PolizaEvento.Categoria.POLIZA,
            tipo=PolizaEvento.Tipo.PERFIL_CAMBIAR,
            severidad="ACTION",
            mensaje="Cambiada foto de perfil",
            data={
                "url_anterior": old.foto_perfil_url,
                "url_nueva": instance.foto_perfil_url,
                "public_id_anterior": old.foto_perfil_public_id,
                "public_id_nuevo": instance.foto_perfil_public_id,
            },
            subject=instance,
            source="SYSTEM",
        )

# ---- Cuotas y pagos (se conectan si existen esos modelos) ----
def _connect_optional_signals():
    try:
        from pagos.models import Pago, Cuota  # ajustá el path real si difiere
    except Exception:
        return

    @receiver(post_save, sender=Cuota)
    def cuota_creada(sender, instance: Cuota, created, **kwargs):
        if created:
            create_event(
                poliza=instance.poliza,
                categoria=PolizaEvento.Categoria.CUOTA,
                tipo=PolizaEvento.Tipo.CUOTA_GENERAR,
                severidad="INFO",
                mensaje="Cuota generada",
                data={"cuota_id": instance.id, "numero": getattr(instance, "numero", None), "importe": float(getattr(instance, "importe", 0) or 0)},
                subject=instance,
                source="SYSTEM",
            )

    @receiver(post_save, sender=Pago)
    def pago_registrado(sender, instance: Pago, created, **kwargs):
        if created:
            create_event(
                poliza=instance.poliza,
                categoria=PolizaEvento.Categoria.PAGO,
                tipo=PolizaEvento.Tipo.PAGO_REGISTRAR,
                severidad="ACTION",
                mensaje="Pago registrado",
                data={
                    "pago_id": instance.id,
                    "monto": float(getattr(instance, "monto", 0) or 0),
                    "moneda": getattr(instance, "moneda", "ARS"),
                    "medio": getattr(instance, "medio", "desconocido"),
                },
                subject=instance,
                source="SYSTEM",
            )

try:
    _connect_optional_signals()
except Exception:
    pass
