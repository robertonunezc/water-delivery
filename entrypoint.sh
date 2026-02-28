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

echo "Running database migrations..."
python manage.py migrate --noinput 

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn server..."
exec gunicorn --bind 0.0.0.0:8000 water_delivery.wsgi:application

echo "Test health check endpoint..."
for i in {1..30}; do
  if curl -fsS http://agua.puntoreica.com/health/ >/dev/null; then
    echo "✅ Ready"
    exit 0
  fi
  sleep 2
done
echo "❌ Not ready"
exit 1