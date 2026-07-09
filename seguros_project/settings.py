"""
Django settings for seguros_project project.
"""

from pathlib import Path
import os
from urllib.parse import urlparse, unquote
from datetime import timedelta # 🚀 IMPORTANTE PARA JWT

BASE_DIR = Path(__file__).resolve().parent.parent

# ✅ Actualizada: Llave más larga para evitar el InsecureKeyLengthWarning en JWT
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-thames-seguros-super-secret-key-2026-catan-32chars")

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
                # 3) Fallback final: tus DB_*
                DATABASES = {
                    'default': {
                        'ENGINE': 'django.db.backends.postgresql',
                        'NAME': os.getenv('DB_NAME', 'railway'),
                        'USER': os.getenv('DB_USER', 'postgres'),
                        'PASSWORD': os.getenv('DB_PASSWORD', ''),
                        'HOST': os.getenv('DB_HOST', 'postgres.railway.internal'),
                        'PORT': os.getenv('DB_PORT', '5432'),
                    }
                }

        # ✅ Ajustes útiles para Railway
        DATABASES['default']['CONN_MAX_AGE'] = int(os.getenv("DB_CONN_MAX_AGE", "60"))
        DATABASES['default']['OPTIONS'] = {
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
        }

        if not all([DATABASES['default'].get('NAME'), DATABASES['default'].get('USER')]):
            raise ValueError("❗ Faltan variables de entorno críticas para la base de datos")
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
ULTRAMSG_INSTANCE_ID = os.getenv("ULTRAMSG_INSTANCE_ID", "")
ULTRAMSG_TOKEN = os.getenv("ULTRAMSG_TOKEN", "")
ULTRAMSG_DEFAULT_CC = os.getenv("ULTRAMSG_DEFAULT_CC", "54")  # Argentina
ULTRAMSG_TIMEOUT = int(os.getenv("ULTRAMSG_TIMEOUT", "12"))
ULTRAMSG_SIMULATE = os.getenv("ULTRAMSG_SIMULATE", "false").lower() == "true"

# ✅ Credenciales por oficina
ULTRAMSG_OFICINA_1_INSTANCE_ID = os.getenv("ULTRAMSG_OFICINA_1_INSTANCE_ID", "instance117665")
ULTRAMSG_OFICINA_1_TOKEN = os.getenv("ULTRAMSG_OFICINA_1_TOKEN", "xa1uqe7gmz9uwuim")

ULTRAMSG_OFICINA_2_INSTANCE_ID = os.getenv("ULTRAMSG_OFICINA_2_INSTANCE_ID", "instance154711")
ULTRAMSG_OFICINA_2_TOKEN = os.getenv("ULTRAMSG_OFICINA_2_TOKEN", "inamppy2y6depv5z")

ULTRAMSG_OFICINA_3_INSTANCE_ID = os.getenv("ULTRAMSG_OFICINA_3_INSTANCE_ID", "instance156893")
ULTRAMSG_OFICINA_3_TOKEN = os.getenv("ULTRAMSG_OFICINA_3_TOKEN", "k71zxdbqqxultdc5")

# 🚀 NUEVA INSTANCIA 4: Home Office - Ventas
ULTRAMSG_OFICINA_4_INSTANCE_ID = os.getenv("ULTRAMSG_OFICINA_4_INSTANCE_ID", "instance171359")
ULTRAMSG_OFICINA_4_TOKEN = os.getenv("ULTRAMSG_OFICINA_4_TOKEN", "ez0cz6q7kiucqryo")

ALIAS_CBU = os.getenv("ALIAS_CBU", "starkeseguros.mp")

# ── Flags de Solicitudes ─────────────────────────────────────────────────────
SOLICITUDES_AUTO_REPLICAR = True
SOLICITUDES_SOBREESCRIBIR_DOCS_CLIENTE = True
SOLICITUDES_AUTO_SET_FOTO_PERFIL = True
SOLICITUDES_SOBREESCRIBIR_FOTO_PERFIL = True

ULTRAMSG_BALANCE_PHONE = os.getenv("ULTRAMSG_BALANCE_PHONE", "1164235336")

# ── Email (SMTP Outlook / Office 365) ─────────────────────────────────────────
# En desarrollo usamos las credenciales de prueba hardcodeadas.
# En producción Railway inyecta las variables de entorno.
EMAIL_BACKEND       = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT          = 587
EMAIL_USE_TLS       = True
EMAIL_USE_SSL       = False
EMAIL_HOST_USER     = os.getenv("EMAIL_HOST_USER", "estudiointegralthames@gmail.com")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "xeve fain fpel eomu")
DEFAULT_FROM_EMAIL  = os.getenv("EMAIL_HOST_USER", "estudiointegralthames@gmail.com")

# Nombre que aparece en el cuerpo del email como remitente
EMAIL_REMITENTE_NOMBRE = os.getenv("EMAIL_REMITENTE_NOMBRE", "Thames Seguros")

# ── TIP: para desarrollo sin mandar emails reales, reemplazá EMAIL_BACKEND por:
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# Así los emails se imprimen en la consola en vez de enviarse.