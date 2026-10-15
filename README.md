# Zainussunna Academy — Calendar Fund Management System (Backend API)

Production Django REST Framework backend for Zainussunna Academy Calendar Manager (ZCM).

## Architecture

- **Framework**: Django 5.2 (REST Framework, SimpleJWT)
- **Database**: PostgreSQL (Neon Serverless with connection pooling)
- **Deployment Runtime**: Vercel Serverless (`@vercel/python` via WSGI entry `api/index.py`)
- **Domain**: `https://api-calendar.zainussunnaacademy.com`

## Environment Variables

Configure the following environment variables in Vercel:

| Variable | Description |
|---|---|
| `DEBUG` | Set to `False` in production |
| `SECRET_KEY` | High-entropy production Django secret key |
| `ALLOWED_HOSTS` | `api-calendar.zainussunnaacademy.com,.vercel.app` |
| `DATABASE_URL` | Neon PostgreSQL pooled connection string (`?sslmode=require`) |
| `CORS_ALLOWED_ORIGINS` | `https://calendar.zainussunnaacademy.com` |
| `TIME_ZONE` | `Asia/Kolkata` |

## Local Development & Testing

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
pytest core/tests.py -v
```
