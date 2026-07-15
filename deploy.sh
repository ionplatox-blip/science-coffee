#!/bin/bash
# ============================================================
# Deploy Science Coffee Bot to production server
# Usage: ./deploy.sh
# ============================================================

set -euo pipefail

SERVER="root@95.181.175.238"
REMOTE_DIR="/opt/science-coffee"
SSH_KEY="$HOME/vpn-chain/bot/deploy_key"
SSH="ssh -i $SSH_KEY $SERVER"
SCP="scp -i $SSH_KEY -r"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}▸ Deploying Science Coffee Bot...${NC}"

# 1. Create directory on server
echo -e "${YELLOW}▸ Creating remote directory...${NC}"
$SSH "mkdir -p $REMOTE_DIR/data $REMOTE_DIR/logs $REMOTE_DIR/bot"

# 2. Upload project files (clean remote bot/ first to avoid nesting)
echo -e "${YELLOW}▸ Uploading files...${NC}"
$SSH "rm -rf $REMOTE_DIR/bot"
$SCP bot "$SERVER:$REMOTE_DIR/"
scp -i $SSH_KEY requirements.txt "$SERVER:$REMOTE_DIR/"
scp -i $SSH_KEY avatar.jpg "$SERVER:$REMOTE_DIR/"
scp -i $SSH_KEY science-coffee.service "$SERVER:$REMOTE_DIR/"
scp -i $SSH_KEY .env.example "$SERVER:$REMOTE_DIR/"

# 3. Upload .env only if it doesn't exist on server
$SSH "test -f $REMOTE_DIR/.env" 2>/dev/null || {
    echo -e "${YELLOW}▸ Uploading .env (first deploy)...${NC}"
    scp -i $SSH_KEY .env "$SERVER:$REMOTE_DIR/.env"
}

# 4. Install dependencies
echo -e "${YELLOW}▸ Installing dependencies...${NC}"
$SSH "cd $REMOTE_DIR && python3 -m pip install -r requirements.txt --break-system-packages -q"

# 5. Install and restart systemd service
echo -e "${YELLOW}▸ Setting up systemd service...${NC}"
$SSH "cp $REMOTE_DIR/science-coffee.service /etc/systemd/system/ && \
      systemctl daemon-reload && \
      systemctl enable science-coffee && \
      systemctl restart science-coffee"

# 6. Check status
echo -e "${YELLOW}▸ Checking status...${NC}"
sleep 2
$SSH "systemctl status science-coffee --no-pager -l" || true

echo -e "${GREEN}✅ Deploy complete!${NC}"
echo -e "Logs: ssh $SERVER 'journalctl -u science-coffee -f'"
