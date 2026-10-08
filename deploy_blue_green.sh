
#!/bin/bash
set -e

NGINX_CONF="/etc/nginx/conf.d/cdp.activation.conf"

docker compose -f docker-compose.prod.yml pull

echo "Restarting background workers..."
docker compose -f docker-compose.prod.yml up -d dashboard cdc-poller scoring-consumer nba-publisher ws-forwarder webhook-forwarder

if grep -q "^ *server 127.0.0.1:8001;" $NGINX_CONF; then
    ACTIVE="blue"
    IDLE="green"
else
    ACTIVE="green"
    IDLE="blue"
fi

echo "Deploying to: $IDLE..."
docker compose -f docker-compose.prod.yml up -d api-$IDLE

# 1. Figure out which local port we need to ping
if [ "$IDLE" == "blue" ]; then
    IDLE_PORT=8001
else
    IDLE_PORT=8002
fi

echo "Waiting for $IDLE to fully boot on port $IDLE_PORT..."

# 2. Ping the container every 2 seconds (up to 30 times / 60 seconds)
for i in {1..30}; do
    # We hit the /docs endpoint because we know FastAPI generates it automatically
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$IDLE_PORT/docs || true)
    
    if [ "$HTTP_STATUS" == "200" ]; then
        echo "Success! $IDLE is fully booted and responding to traffic."
        break
    fi
    
    echo "Still booting... (Attempt $i/30)"
    sleep 2
done

# 3. Abort the deployment if it never booted properly
if [ "$HTTP_STATUS" != "200" ]; then
    echo "CRITICAL ERROR: The new code in $IDLE failed to start within 60 seconds!"
    echo "Aborting deployment to protect production traffic."
    docker compose -f docker-compose.prod.yml stop api-$IDLE
    exit 1 # This tells GitLab to mark the pipeline as FAILED
fi

# We use sudo here because this file is owned by root
# 1. Forcefully comment out BOTH lines just to be safe
sudo sed -i 's/.*127.0.0.1:8001.*/    # server 127.0.0.1:8001; # BLUE/' $NGINX_CONF
sudo sed -i 's/.*127.0.0.1:8002.*/    # server 127.0.0.1:8002; # GREEN/' $NGINX_CONF

# 2. Uncomment only the active one
if [ "$IDLE" == "blue" ]; then
    sudo sed -i 's/.*127.0.0.1:8001.*/    server 127.0.0.1:8001; # BLUE/' $NGINX_CONF
else
    sudo sed -i 's/.*127.0.0.1:8002.*/    server 127.0.0.1:8002; # GREEN/' $NGINX_CONF
fi

# 3. Reload Nginx
sudo systemctl reload nginx

# Reload host Nginx
sudo systemctl reload nginx

docker compose -f docker-compose.prod.yml stop api-$ACTIVE
echo "Deployment complete! $IDLE is now live."
