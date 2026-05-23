FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client=17+278 \
        curl=8.14 \
        gcc=4:14.2.0-1 \
        python3-dev=3.13.5-1 \
        libpq-dev=17.10-0+deb13u1 \
        netcat-traditional=1.10-50 \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Copy and make entrypoint script executable
COPY entrypoint.sh /app/
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Create runtime directories
RUN mkdir -p /app/staticfiles /app/logs

# Expose port
EXPOSE 80

# Run the application
CMD ["/app/entrypoint.sh"]