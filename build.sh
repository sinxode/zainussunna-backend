#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo "🎨 Collecting static files..."
python manage.py collectstatic --no-input

echo "🗄️ Running database migrations..."
python manage.py migrate --no-input

echo "⚙️ Initializing system data (Programs, Configs)..."
python manage.py init_system

echo "🔑 Creating default superuser (if none exists)..."
python manage.py shell -c "
from django.contrib.auth import get_user_model;
User = get_user_model();
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser('admin', 'admin@zainussunnaacademy.com', 'Admin@12345')
    print('✅ Default admin created: Username: admin | Password: Admin@12345')
else:
    print('✅ Superuser already exists. Skipping creation.')
"

echo "✅ Build script completed successfully!"