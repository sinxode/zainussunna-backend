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
# FIX: Hardcoded ALLOWED_HOSTS (User Recommended)
# ==========================================
# Do not rely on environment variables until everything works.
ALLOWED_HOSTS = [
    "api.zainussunnaacademy.com",
    "zainussunnaacademy.com",
    "www.zainussunnaacademy.com",
    "zainussunna-backend.onrender.com",
    ".onrender.com",
]

# ==========================================
# FIX: Hardcoded CORS Parsing
# ==========================================
CORS_ALLOWED_ORIGINS = [
    'https://zainussunnaacademy.com',
    'https://www.zainussunnaacademy.com',
    'https://api.zainussunnaacademy.com',
]

CORS_ALLOW_ALL_ORIGINS = False

# Static and Media files - use WhiteNoise
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Logging - more verbose in production
LOGGING['loggers']['django']['level'] = 'WARNING'
LOGGING['loggers']['core']['level'] = 'WARNING'

