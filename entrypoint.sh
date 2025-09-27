#!/bin/bash

set -e

echo "Waiting for database..."
while ! nc -z postgres 5432; do
    sleep 1
done
echo "Database is ready!"

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn server..."
exec gunicorn --bind 0.0.0.0:8000 water_delivery.wsgi:application