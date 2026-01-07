#!/bin/bash
# EventFlow - AWS EC2 Deployment Script
# Run with: sudo bash deploy.sh [your-domain.com]
# For IP-only: sudo bash deploy.sh

set -e

DOMAIN=${1:-""}
APP_DIR="/opt/eventflow"
DOCKER_USER="ashishkrshaw"

echo "============================================"
echo "  EventFlow Deployment Script"
echo "  Target: Amazon Linux 2023"
echo "============================================"

# check root
if [ "$EUID" -ne 0 ]; then
  echo "Please run with sudo"
  exit 1
fi

# install docker
echo "[1/7] Installing Docker..."
if ! command -v docker &> /dev/null; then
  dnf update -y
  dnf install -y docker
  systemctl start docker
  systemctl enable docker
  usermod -aG docker ec2-user
  echo "Docker installed"
else
  echo "Docker already installed"
fi

# install docker compose
echo "[2/7] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
  curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
  ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose
  echo "Docker Compose installed"
else
  echo "Docker Compose already installed"
fi

# install nginx
echo "[3/7] Installing Nginx..."
if ! command -v nginx &> /dev/null; then
  dnf install -y nginx
  systemctl enable nginx
  echo "Nginx installed"
else
  echo "Nginx already installed"
fi

# create app directory
echo "[4/7] Setting up application..."
mkdir -p $APP_DIR
cd $APP_DIR

# create .env file if not exists
if [ ! -f "$APP_DIR/.env" ]; then
  cat > $APP_DIR/.env << 'ENVEOF'
# Redis
REDIS_URL=redis://redis:6379

# Email (SMTP) - Configure for real emails
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
FROM_EMAIL=

# Email Rate Limiting
DAILY_EMAIL_LIMIT=20
ALERT_EMAIL=your-admin-email@example.com

# App
LOG_LEVEL=INFO
MAX_RETRIES=3
ENVEOF
  echo "Created .env file - edit with your email credentials"
else
  echo ".env already exists"
fi

# create docker-compose.yml
cat > $APP_DIR/docker-compose.yml << EOF
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    image: ${DOCKER_USER}/eventflow-api:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      redis:
        condition: service_healthy

  worker:
    image: ${DOCKER_USER}/eventflow-worker:latest
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      redis:
        condition: service_healthy

volumes:
  redis_data:
EOF

echo "Created docker-compose.yml"

# nginx config
echo "[5/7] Configuring Nginx..."

if [ -n "$DOMAIN" ]; then
  # with domain
  cat > /etc/nginx/conf.d/eventflow.conf << EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /metrics {
        proxy_pass http://127.0.0.1:8000/metrics;
        # optionally restrict to internal
    }
}
EOF
else
  # ip only
  cat > /etc/nginx/conf.d/eventflow.conf << EOF
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
fi

# remove default nginx config if exists
rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true

nginx -t && systemctl restart nginx
echo "Nginx configured"

# setup https if domain provided
if [ -n "$DOMAIN" ]; then
  echo "[5.5/7] Setting up HTTPS with Let's Encrypt..."
  if ! command -v certbot &> /dev/null; then
    dnf install -y certbot python3-certbot-nginx
  fi
  certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN --redirect || echo "Certbot failed - you can run manually later"
fi

# pull and start containers
echo "[6/7] Starting services..."
cd $APP_DIR
docker-compose pull
docker-compose up -d

# create helper scripts
echo "[7/7] Creating helper scripts..."

# status.sh
cat > $APP_DIR/status.sh << 'EOF'
#!/bin/bash
echo "=== Container Status ==="
docker-compose ps
echo ""
echo "=== Health Check ==="
curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "API not responding"
echo ""
echo "=== Queue Stats ==="
curl -s http://localhost:8000/stats | python3 -m json.tool 2>/dev/null || echo "Stats not available"
EOF

# logs.sh
cat > $APP_DIR/logs.sh << 'EOF'
#!/bin/bash
SERVICE=${1:-""}
if [ -n "$SERVICE" ]; then
  docker-compose logs -f --tail=100 $SERVICE
else
  docker-compose logs -f --tail=100
fi
EOF

# update.sh
cat > $APP_DIR/update.sh << 'EOF'
#!/bin/bash
echo "Pulling latest images..."
docker-compose pull
echo "Restarting services..."
docker-compose up -d
echo "Cleaning old images..."
docker image prune -f
echo "Done!"
EOF

# restart.sh
cat > $APP_DIR/restart.sh << 'EOF'
#!/bin/bash
docker-compose restart
echo "Services restarted"
EOF

chmod +x $APP_DIR/*.sh

# get public ip
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "your-ip")

echo ""
echo "============================================"
echo "  Deployment Complete!"
echo "============================================"
echo ""
echo "Service URLs:"
if [ -n "$DOMAIN" ]; then
  echo "  API:      https://$DOMAIN"
  echo "  Docs:     https://$DOMAIN/docs"
  echo "  Health:   https://$DOMAIN/health"
  echo "  Metrics:  https://$DOMAIN/metrics"
else
  echo "  API:      http://$PUBLIC_IP"
  echo "  Docs:     http://$PUBLIC_IP/docs"
  echo "  Health:   http://$PUBLIC_IP/health"
  echo "  Metrics:  http://$PUBLIC_IP/metrics"
fi
echo ""
echo "Helper scripts in $APP_DIR:"
echo "  ./status.sh   - check service health"
echo "  ./logs.sh     - view logs (./logs.sh api)"
echo "  ./update.sh   - pull latest and restart"
echo "  ./restart.sh  - restart services"
echo ""
echo "Edit email config:"
echo "  nano $APP_DIR/.env"
echo "  ./restart.sh"
echo ""
echo "Done!"
