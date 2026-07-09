# usuarios/serializers.py
from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Oficina, Perfil

class OficinaSerializer(serializers.ModelSerializer):
    # 🚀 NUEVO: Campo extra para ver el nombre en la tabla del frontend sin esfuerzo
    responsable_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Oficina
        fields = '__all__'

    def get_responsable_nombre(self, obj):
        if obj.responsable:
            nombre_completo = f"{obj.responsable.first_name} {obj.responsable.last_name}".strip()
            return nombre_completo if nombre_completo else obj.responsable.username
        return "Sin asignar"

class PerfilSerializer(serializers.ModelSerializer):
    oficina_codigo = serializers.CharField(source='oficina.codigo', read_only=True)
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)

    class Meta:
        model = Perfil
        fields = ['rol', 'oficina', 'oficina_codigo', 'oficina_nombre']

class UserSerializer(serializers.ModelSerializer):
    perfil = PerfilSerializer(read_only=True)
    
    # Campos virtuales para permitir creación/edición desde el frontend
    password = serializers.CharField(write_only=True, required=False)
    rol = serializers.ChoiceField(choices=Perfil.ROL_CHOICES, write_only=True, required=False)
    oficina = serializers.PrimaryKeyRelatedField(
        queryset=Oficina.objects.all(), write_only=True, required=False, allow_null=True
    )
    
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'perfil', 'password', 'rol', 'oficina']

    def create(self, validated_data):
        # Separamos los datos extra
        password = validated_data.pop('password', None)
        rol = validated_data.pop('rol', 'OFICINA')
        oficina = validated_data.pop('oficina', None)
        
        # Creamos el usuario base
        user = User(**validated_data)
        if password:
            user.set_password(password)  # Esto encripta la clave de forma segura
        user.save() # El signal (en models.py) automáticamente le crea un Perfil vacío
        
        # Le inyectamos el Rol y la Oficina a su nuevo perfil
        user.perfil.rol = rol
        user.perfil.oficina = oficina
        user.perfil.save()
        
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        rol = validated_data.pop('rol', None)
        oficina = validated_data.pop('oficina', None)
        
        # Actualizamos datos del User base (nombre, email, username)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
            
        if password:
            instance.set_password(password)
        instance.save()
        
        # Actualizamos el Perfil si enviaron los datos
        if rol is not None:
            instance.perfil.rol = rol
            
        # Revisamos initial_data para permitir asignar valor null a la oficina
        if 'oficina' in self.initial_data:
            instance.perfil.oficina = oficina
            
        instance.perfil.save()
        return instance