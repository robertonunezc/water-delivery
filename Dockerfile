FROM python:3.12-slim-trixie@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
ARG DEBIAN_SNAPSHOT=20260817T000000Z
ARG DEBIAN_FRONTEND=noninteractive

RUN printf '%s\n' \
        "deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} trixie main" \
        "deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} trixie-updates main" \
        "deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} trixie-security main" \
        > /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client=17+278 \
        curl=8.14.1-2+deb13u4 \
        gcc=4:14.2.0-1 \
        python3-dev=3.13.5-1 \
        libpq-dev=17.11-0+deb13u1 \
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
