"""
Production Settings for Academic Admission System
Optimized for deployment on Render.com
"""
from .settings import *  # Import all base settings
import os
import random
import string

# Override security settings for production

# Force HTTPS in production
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS settings
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Cookie security
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Disable DEBUG in production
DEBUG = False

# Generate a proper SECRET_KEY for production if not set
if not SECRET_KEY or SECRET_KEY == 'django-insecure-dev-key-for-local-development-only-change-in-production':
    chars = string.ascii_letters + string.digits + string.punctuation
    SECRET_KEY = ''.join(random.choice(chars) for _ in range(64))
    print("⚠️  WARNING: Generated new SECRET_KEY. Set DJANGO_SECRET_KEY environment variable for persistence!")

# ==========================================
# FIX: Robust ALLOWED_HOSTS Parsing (Resolves 400 Bad Request)
# ==========================================
# If ALLOWED_HOSTS is provided via Render ENV, parse it.
env_hosts = os.environ.get('ALLOWED_HOSTS', '')
ALLOWED_HOSTS = [h.strip() for h in env_hosts.split(',')] if env_hosts else []

# CRITICAL: Always ensure the Render domain and primary domains are permitted.
# Note: Django uses '.domain.com' for wildcards, NOT '*.domain.com'
required_hosts = [
    'zainussunnaacademy.com',
    'www.zainussunnaacademy.com',
    'api.zainussunnaacademy.com',
    'zainussunna-backend.onrender.com',
    '.onrender.com', 
]

for host in required_hosts:
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

# ==========================================
# FIX: Robust CORS Parsing
# ==========================================
env_cors = os.environ.get('CORS_ALLOWED_ORIGINS', '')
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in env_cors.split(',')] if env_cors else []

required_cors = [
    'https://zainussunnaacademy.com',
    'https://www.zainussunnaacademy.com',
]

for origin in required_cors:
    if origin not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(origin)

CORS_ALLOW_ALL_ORIGINS = False

# Static and Media files - use WhiteNoise
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Logging - more verbose in production
LOGGING['loggers']['django']['level'] = 'WARNING'
LOGGING['loggers']['core']['level'] = 'WARNING'

