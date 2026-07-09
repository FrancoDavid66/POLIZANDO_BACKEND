# usuarios/mixins.py
from django.core.exceptions import FieldDoesNotExist, FieldError
from django.db.models import Q

class MultiTenantMixin:
    """
    Mixin de Seguridad para ViewSets (Escudo Multi-tenant Blindado).
    Filtra automáticamente los datos según el rol, la oficina o el vendedor.
    """
    tenant_field = 'oficina'
    vendedor_field = 'vendedor'  # 🚀 NUEVO: Campo para filtrar por vendedor

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        # 1. Protección básica: Si no está logueado, no ve nada
        if not user.is_authenticated:
            return qs.none()

        # Obtenemos los campos por los cuales filtrar
        t_field = getattr(self, 'tenant_field', 'oficina')
        v_field = getattr(self, 'vendedor_field', 'vendedor')

        # 2. ¿Es Administrador?
        is_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')

        # 3. CASO ADMIN: Ve todo, pero puede filtrar por URL
        if is_admin:
            oficina_param = self.request.query_params.get("oficina")

            # Si no hay parámetro o es "ALL", ve TODO
            if not oficina_param or str(oficina_param).upper() in ["ALL", "NULL", "UNDEFINED", ""]:
                return qs

            # Si hay parámetro numérico, filtramos por ID de la oficina
            if str(oficina_param).isdigit():
                return qs.filter(**{f"{t_field}": int(oficina_param)})

            # Si es texto (ej: "5 ESQUINAS"), buscamos por CÓDIGO o NOMBRE de la oficina.
            # OJO: 'oficina' es una relación (ForeignKey), por eso NO se puede usar
            # oficina__iexact directo (Django lo rechaza). Se busca dentro de la relación.
            try:
                return qs.filter(
                    Q(**{f"{t_field}__codigo__iexact": oficina_param}) |
                    Q(**{f"{t_field}__nombre__iexact": oficina_param})
                )
            except FieldError:
                # Compatibilidad vieja: si 'oficina' fuese un CharField de texto plano.
                return qs.filter(**{f"{t_field}__iexact": oficina_param})

        # 4. 🚀 CASO VENDEDOR: Filtro estricto (Solo ve los registros vinculados a su perfil)
        if hasattr(user, 'perfil') and user.perfil.rol == 'VENDEDOR':
            try:
                return qs.filter(**{v_field: user.perfil})
            except (FieldError, FieldDoesNotExist, Exception):
                # Parche de seguridad: Si el modelo no tiene el campo 'vendedor_field',
                # no rompemos la app, simplemente no mostramos nada.
                return qs.none()

        # 5. 🔓 CASO OFICINA (Usuario de Sucursal): VE Y OPERA CON TODO.
        #    Decisión de negocio: un cliente pertenece a su oficina original, pero
        #    cualquier oficina puede verlo y operar (dar de alta, cobrar, etc.) porque
        #    los clientes circulan entre sucursales. La plata (recaudación/métricas)
        #    se sigue separando por oficina en SUS propios módulos (no acá).
        #    Igual respetamos el filtro opcional ?oficina= si lo mandan a propósito.
        oficina_param = self.request.query_params.get("oficina")
        if oficina_param and str(oficina_param).upper() not in ["ALL", "NULL", "UNDEFINED", ""]:
            if str(oficina_param).isdigit():
                return qs.filter(**{f"{t_field}": int(oficina_param)})
            try:
                return qs.filter(
                    Q(**{f"{t_field}__codigo__iexact": oficina_param}) |
                    Q(**{f"{t_field}__nombre__iexact": oficina_param})
                )
            except FieldError:
                return qs.filter(**{f"{t_field}__iexact": oficina_param})

        # Sin filtro explícito → ve TODO.
        return qs