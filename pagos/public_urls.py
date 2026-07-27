# pagos/public_urls.py
"""
Rutas PÚBLICAS de pagos (sin autenticación).

Se montan bajo /public/pagos/ (ver seguros_project/urls.py):
    path('public/pagos/', include('pagos.public_urls')),

- mp/webhook/                         → lo llama Mercado Pago (notificaciones).
- portal/<token>/mp/crear-preferencia/ → lo llama el Portal del Asegurado
                                         (el cliente paga su cuota, sin login).
"""
from django.urls import path

from . import mercadopago_pagos
from . import mercadopago_portal

urlpatterns = [
    path("mp/webhook/", mercadopago_pagos.webhook, name="mp-webhook"),
    path(
        "portal/<str:token>/mp/crear-preferencia/",
        mercadopago_portal.crear_preferencia_portal,
        name="mp-portal-crear-preferencia",
    ),
]