.PHONY: help install migrate runserver test lint format clean shell collectstatic celery-worker celery-beat

help:
	@echo "Available commands:"
	@echo "  install      - Install dependencies"
	@echo "  migrate      - Run database migrations"
	@echo "  runserver    - Start development server"
	@echo "  test         - Run tests"
	@echo "  lint         - Run linting"
	@echo "  format       - Format code"
	@echo "  clean        - Clean cache files"
	@echo "  shell        - Open Django shell"
	@echo "  collectstatic - Collect static files"
	@echo "  celery-worker - Start Celery worker"
	@echo "  celery-beat   - Start Celery beat scheduler"

install:
	pip install -r requirements.txt

migrate:
	python manage.py makemigrations
	python manage.py migrate

runserver:
	python manage.py runserver 0.0.0.0:8002

test:
	python manage.py test

lint:
	flake8 .
	pylint **/*.py

format:
	black .
	isort .

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete

shell:
	python manage.py shell

collectstatic:
	python manage.py collectstatic --noinput

celery-worker:
	celery -A water_delivery worker -l info

celery-beat:
	celery -A water_delivery beat -l info