"""Django settings for the Ice Factory Management System.

Configuration comes from the environment (see .env.example). Nothing secret
is hard-coded here. Production requires DEBUG=False, a real SECRET_KEY and
a DATABASE_URL pointing at PostgreSQL 16.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    env.read_env(ENV_FILE, overwrite=False)

DEBUG = env("DEBUG")

SECRET_KEY = env("SECRET_KEY", default=None)
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-dev-only-key-do-not-use-in-production"
    else:
        raise ValueError("SECRET_KEY must be set in the environment for production.")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# DEBUG must never serve a public host: with DEBUG on, a bad URL shows a
# full traceback (settings, paths, SQL). Local hosts are allowed because
# the documented local test — phone on the same Wi-Fi — needs a LAN
# address in ALLOWED_HOSTS; anything public is refused at startup.
if DEBUG:
    import ipaddress

    def _is_local_host(host):
        host = host.strip().lower()
        if host in ("localhost", "[::1]") or host.endswith(".localhost"):
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # A hostname that is not localhost is treated as public:
            # resolving it at startup would add a DNS dependency.
            return False
        return address.is_loopback or not address.is_global

    public_hosts = [h for h in ALLOWED_HOSTS if not _is_local_host(h)]
    if public_hosts:
        raise ValueError(
            "DEBUG=True is not allowed with a public host in ALLOWED_HOSTS "
            f"({', '.join(public_hosts)}). Set DEBUG=False for a live host, "
            "or keep ALLOWED_HOSTS to localhost / your local network only."
        )

# CSRF: trust the same hosts we serve. An explicit env value wins;
# otherwise derive https:// origins from ALLOWED_HOSTS, so a new live
# host (Render, VPS domain) works by setting ALLOWED_HOSTS alone.
# Without this, login and every other POST fail CSRF on a new domain.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}"
        for host in ALLOWED_HOSTS
        if host and "*" not in host and not host.startswith(".")
    ]

# Non-default admin URL, taken from the environment (superusers only).
ADMIN_URL = env("ADMIN_URL", default="site-admin/").strip("/") + "/"

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "axes",
    "core",
    "accounts",
    "customers",
    "sales",
    "expenses",
    "employees",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "axes.middleware.AxesMiddleware",
    "core.middleware.HtmxLoginRedirectMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.factory_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database: PostgreSQL 16 in production via DATABASE_URL. Local development
# falls back to SQLite so the project runs without a server installed.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Login rate limiting: lock after 5 failed logins for 15 minutes, per
# (username, IP) combination — a nested list means the pair is the key,
# so a different IP (or a different username) is not locked out by
# someone else's failures. The real client IP behind Nginx comes from
# core.axes_ip (last X-Forwarded-For entry, i.e. the address Nginx saw);
# without it, axes would fall back to REMOTE_ADDR and every visitor
# behind the proxy would share one lockout bucket.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_CLIENT_IP_CALLABLE = "core.axes_ip.get_client_ip"
AXES_RESET_ON_SUCCESS = True

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# Sessions: 7 days, sliding (refreshed on every request), HttpOnly, Lax.
SESSION_COOKIE_AGE = 7 * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"

# HTTPS-only in production (behind Nginx with the proxy header set).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

# Error logs go to a rotating file; users never see stack traces.
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "django.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["file"], "level": "ERROR"},
}
