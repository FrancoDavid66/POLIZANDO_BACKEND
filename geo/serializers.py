# geo/serializers.py
from rest_framework import serializers
from .models import GeoItem


class GeoItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoItem
        fields = "__all__"
        read_only_fields = ("creado_en",)
