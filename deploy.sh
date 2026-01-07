#!/bin/bash
# A simple script I wrote to deploy my EventFlow project to EC2.
# It installs Docker, pulls my images, and sets up Nginx with DuckDNS.

echo "--- EventFlow Deployer ---"

# Step 1: Ask for details
read -p "Your DuckDNS Domain (e.g. name.duckdns.org): " DOMAIN
read -p "Your Gmail for SMTP: " EMAIL
read -p "Your Gmail App Password: " PASS
read -p "Your Admin Alert Email: " ALERT

# Step 2: Install Docker if missing
echo "Checking Docker..."
if ! command -v docker &> /dev/null; then
    sudo dnf update -y
    sudo dnf install -y docker
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker ec2-user
fi

# Docker Compose
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    sudo ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose
fi

# Step 3: Setup folders and files
mkdir -p ~/eventflow
cd ~/eventflow

echo "Creating .env file..."
cat > .env << EOF
REDIS_URL=redis://redis:6379
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=$EMAIL
SMTP_PASSWORD=$PASS
FROM_EMAIL=$EMAIL
DAILY_EMAIL_LIMIT=20
ALERT_EMAIL=$ALERT
EOF

echo "Creating docker-compose.yml..."
cat > docker-compose.yml << EOF
version: '3.8'
services:
  redis:
    image: redis:7-alpine
    restart: always

  api:
    image: ashishkrshaw/eventflow-api:latest
    restart: always
    ports:
      - "8005:8000"
    env_file: .env
    depends_on:
      - redis

  worker:
    image: ashishkrshaw/eventflow-worker:latest
    restart: always
    env_file: .env
    depends_on:
      - redis
EOF

# Step 4: Run the app
echo "Pulling images and starting..."
docker-compose pull
docker-compose up -d

# Step 5: Nginx Setup
echo "Setting up Nginx for $DOMAIN..."
if ! command -v nginx &> /dev/null; then
    sudo dnf install -y nginx
    sudo systemctl start nginx
    sudo systemctl enable nginx
fi

# Simple Nginx config for our domain
sudo bash -c "cat > /etc/nginx/conf.d/eventflow.conf" << EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8005;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

sudo nginx -t && sudo systemctl reload nginx

# Step 6: SSL with DuckDNS
echo "Trying to get SSL certificate..."
if ! command -v certbot &> /dev/null; then
    sudo dnf install -y certbot python3-certbot-nginx
fi

sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email $ALERT --redirect || echo "SSL failed - Check if DuckDNS points to this IP"

echo "Done! You can visit https://$DOMAIN"
