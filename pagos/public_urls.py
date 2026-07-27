# pagos/public_urls.py
"""
Rutas PÚBLICAS de pagos (sin autenticación).

Se montan bajo /public/pagos/ (ver seguros_project/urls.py).
Acá va SOLO el webhook de Mercado Pago, que lo llama Mercado Pago
directamente (no lleva token de tu app).
"""
from django.urls import path

from . import mercadopago_pagos

urlpatterns = [
    path("mp/webhook/", mercadopago_pagos.webhook, name="mp-webhook"),
]