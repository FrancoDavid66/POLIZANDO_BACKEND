"""
Django settings for seguros_project project.
"""

from pathlib import Path
import os
from urllib.parse import urlparse, unquote
from datetime import timedelta  # 🚀 IMPORTANTE PARA JWT

from django.core.exceptions import ImproperlyConfigured  # 🔒 para fallar claro si falta una env var

BASE_DIR = Path(__file__).resolve().parent.parent


def get_required_env(name: str) -> str:
    """
    🔒 Devuelve el valor de la variable de entorno `name`.
    Si no está seteada (o está vacía) NO hay valor por defecto: corta el
    arranque con un error claro en vez de caer silenciosamente en una
    credencial hardcodeada (p. ej. de Thames).
    """
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ImproperlyConfigured(
            f"❌ Falta configurar la variable de entorno obligatoria: {name}. "
            f"Setealá en las variables de entorno de Railway (Polizando)."
        )
    return value


# ✅ SECRET_KEY: sin valor por defecto. Cada proyecto (Thames / Polizando) tiene el suyo.
SECRET_KEY = get_required_env("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = (os.getenv("ALLOWED_HOSTS", "*") or "*").split(",")
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS if h.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'whitenoise.runserver_nostatic',
    'rest_framework',
    'rest_framework_simplejwt', # 🚀 AGREGADO PARA JWT
    'corsheaders',

    'clientes',
    'pagos.apps.PagosConfig',
    'siniestros',
    'geo',
    'inmuebles',
    'alquileres',
    'balanzes',
    'polizas',
    'gruas',
    'historia',
    # ⚠️ Usar AppConfig para cargar señales y evitar duplicado de label:
    'solicitudes.apps.SolicitudesConfig',
    'django_filters',
    'notificaciones',
    'competencia',
    'estadisticas',
    'marketing',
    'bajas',
    'usuarios',
    'recaudacion',
    'cotizaciones',
    'servicios',
    'tareas',
    'ranking'
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'seguros_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'seguros_project.wsgi.application'


def _parse_database_url(db_url: str) -> dict:
    """
    Soporta: postgres://user:pass@host:port/dbname
    """
    u = urlparse(db_url)
    if u.scheme not in ("postgres", "postgresql"):
        raise ValueError(f"Esquema DATABASE_URL no soportado: {u.scheme}")

    name = (u.path or "").lstrip("/")
    if not name:
        raise ValueError("DATABASE_URL no tiene nombre de base (path).")

    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(name),
        'USER': unquote(u.username or ""),
        'PASSWORD': unquote(u.password or ""),
        'HOST': u.hostname or "",
        'PORT': str(u.port or "5432"),
    }


# ── DB: modo segun env ─────────────────────────────────────────────────────────
MODE = os.getenv('DJANGO_ENV', 'production')
is_development = MODE == 'development'

# ✅ DEBUG: en prod default FALSE (si querés activarlo: DJANGO_DEBUG=true)
DEBUG = (os.getenv("DJANGO_DEBUG", "true" if is_development else "false").strip().lower() == "true")

if is_development:
    print("🌱 Modo: Desarrollo")
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    print("🌍 Modo: Producción")
    try:
        # 1) PRIORIDAD: DATABASE_URL (si existe)
        database_url = (os.getenv("DATABASE_URL") or "").strip()
        if database_url:
            DATABASES = {'default': _parse_database_url(database_url)}
        else:
            # 2) Preferir variables PG* (Railway Postgres suele inyectarlas)
            pg_host = os.getenv("PGHOST")
            pg_user = os.getenv("PGUSER")
            pg_password = os.getenv("PGPASSWORD")
            pg_db = os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE")
            pg_port = os.getenv("PGPORT", "5432")

            if pg_host and pg_user and pg_password and pg_db:
                DATABASES = {
                    'default': {
                        'ENGINE': 'django.db.backends.postgresql',
                        'NAME': pg_db,
                        'USER': pg_user,
                        'PASSWORD': pg_password,
                        'HOST': pg_host,
                        'PORT': pg_port,
                    }
                }
            else:
                # 🔒 SIN fallback hardcodeado. Antes acá había defaults tipo
                # DB_HOST="postgres.railway.internal", DB_USER="postgres", etc.
                # que podían hacer que Polizando terminara apuntando a la
                # infraestructura de Thames sin que nadie lo notara.
                raise ImproperlyConfigured(
                    "❌ Falta configurar la base de datos: seteá DATABASE_URL "
                    "(o PGHOST/PGUSER/PGPASSWORD/PGDATABASE) en Railway (Polizando)."
                )

        # ✅ Ajustes útiles para Railway
        DATABASES['default']['CONN_MAX_AGE'] = int(os.getenv("DB_CONN_MAX_AGE", "60"))
        DATABASES['default']['OPTIONS'] = {
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
        }

        if not all([DATABASES['default'].get('NAME'), DATABASES['default'].get('USER')]):
            raise ImproperlyConfigured("❗ Faltan variables de entorno críticas para la base de datos")
    except Exception as e:
        print(f"🚨 Error en la configuración de la base de datos: {e}")
        raise

if is_development:
    print(f"💾 Base de Datos: {DATABASES['default']['ENGINE']}")

# ── Password validators ────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── I18N / TZ ──────────────────────────────────────────────────────────────────
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_TZ = True
LANGUAGE_CODE = "es-ar"

# ── Static / Media ─────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── CORS ───────────────────────────────────────────────────────────────────────
# ⚠️ Sin tocar: sigue apuntando al front de Thames. Cuando exista el repo/dominio
# del front de Polizando, avisame y lo actualizamos (no lo adiviné).
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'https://bd-thames-frontend.vercel.app',
]

CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    "https://bd-thames-frontend.vercel.app",
]

# ── Seguridad adicional ────────────────────────────────────────────────────────
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Railway va detrás de proxy/https
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = (os.getenv("SECURE_SSL_REDIRECT", "false").strip().lower() == "true")

# ── DRF: Paginación y Autenticación JWT ─────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'seguros_project.pagination.LargeResultsSetPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    # 🚀 AGREGADO: React usará JWT para hablar con Django
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
}

# 🚀 CONFIGURACIÓN DE TOKENS (Simple JWT)
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1), # El login dura 1 día
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ── Mensajería / Cobranza (UltraMsg + alias de cobro) ─────────────────────────
# 🔒 El instance ID / token de UltraMsg NO van acá. En Polizando se cargan por
# oficina en el modelo usuarios.Oficina (campos ultramsg_instance_id /
# ultramsg_token, se editan desde el admin) — no hay una cantidad fija de
# oficinas ni credenciales por env var. Ver notificaciones/utils/ultramsg.py.
ULTRAMSG_DEFAULT_CC = os.getenv("ULTRAMSG_DEFAULT_CC", "54")  # Argentina
ULTRAMSG_TIMEOUT = int(os.getenv("ULTRAMSG_TIMEOUT", "12"))
ULTRAMSG_SIMULATE = os.getenv("ULTRAMSG_SIMULATE", "false").lower() == "true"

ALIAS_CBU = get_required_env("ALIAS_CBU")

# 🔒 pagos/utils/medios.py usa esto para el texto "(a nombre de {titular})" en los
# mensajes de cobro. Sin esta línea, ese archivo cae en su propio default hardcodeado
# ("Estudio Thames") porque no encuentra el atributo en settings.
COBRO_TITULAR_NOMBRE = get_required_env("COBRO_TITULAR_NOMBRE")

# ── Flags de Solicitudes ─────────────────────────────────────────────────────
SOLICITUDES_AUTO_REPLICAR = True
SOLICITUDES_SOBREESCRIBIR_DOCS_CLIENTE = True
SOLICITUDES_AUTO_SET_FOTO_PERFIL = True
SOLICITUDES_SOBREESCRIBIR_FOTO_PERFIL = True

ULTRAMSG_BALANCE_PHONE = get_required_env("ULTRAMSG_BALANCE_PHONE")

# ── Email (SMTP) ───────────────────────────────────────────────────────────────
# 🔕 DESACTIVADO: Polizando no usa email. Si en algún momento hace falta,
# descomentá este bloque y cargá las 4 variables en Railway.
# EMAIL_BACKEND       = "django.core.mail.backends.smtp.EmailBackend"
# EMAIL_HOST          = get_required_env("EMAIL_HOST")
# EMAIL_PORT          = 587
# EMAIL_USE_TLS       = True
# EMAIL_USE_SSL       = False
# EMAIL_HOST_USER     = get_required_env("EMAIL_HOST_USER")
# EMAIL_HOST_PASSWORD = get_required_env("EMAIL_HOST_PASSWORD")
# DEFAULT_FROM_EMAIL  = EMAIL_HOST_USER
# EMAIL_REMITENTE_NOMBRE = get_required_env("EMAIL_REMITENTE_NOMBRE")

# Placeholders vacíos (NO son de Thames): si algún management command viejo
# todavía intenta mandar un email, esto lo hace fallar limpio (sin servidor
# configurado) en vez de usar credenciales de Thames o tirar AttributeError.
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
DEFAULT_FROM_EMAIL = ""
EMAIL_REMITENTE_NOMBRE = ""

# ── TIP: para desarrollo sin mandar emails reales, reemplazá EMAIL_BACKEND por:
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# Así los emails se imprimen en la consola en vez de enviarse.