#!/bin/bash

set -e

echo "Waiting for database..."
DB_HOST=${POSTGRES_HOST:-postgres}
DB_PORT=${POSTGRES_PORT:-5432}
echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
while ! nc -z "$DB_HOST" "$DB_PORT"; do
    sleep 1
done
echo "Database is ready!"

echo "Running django-tenants migrations..."
echo "Migrating shared apps (public schema)..."
python manage.py migrate_schemas --shared

echo "Migrating all tenant schemas..."
python manage.py migrate_schemas 

echo "Collecting static files..."
python manage.py collectstatic --noinput

mkdir -p /app/logs

echo "Starting Gunicorn server..."
exec gunicorn --bind 0.0.0.0:8000 \
         --workers 3 \
         --timeout 60 \
         --access-logfile /app/logs/gunicorn-access.log \
         --error-logfile /app/logs/gunicorn-error.log \
         water_delivery.wsgi:application