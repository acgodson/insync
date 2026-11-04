#!/bin/bash
# Deploy InSync (backend + tools + web) to the EC2 host: rsync, venv, models, systemd, Caddy. One command.
set -e
HOST="${INSYNC_HOST:-13.216.97.225}"
KEY="${INSYNC_KEY:-$HOME/.ssh/insync-regina.pem}"
DOMAIN="insync.$(echo "$HOST" | tr . -).sslip.io"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no ubuntu@$HOST"

echo "== rsync to $HOST"
rsync -az --delete -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
  --exclude '.venv' --exclude '__pycache__' --exclude 'uploads' --exclude 'data/kaggle' --exclude 'index.original.html' \
  "$ROOT/backend" "$ROOT/tools" "$ROOT/web" "$ROOT/deploy" ubuntu@"$HOST":/opt/insync/

echo "== remote setup"
$SSH "DOMAIN=$DOMAIN bash -s" <<'EOF'
set -e
sudo apt-get install -y -q libgl1 libegl1 libgles2 libglib2.0-0 >/dev/null
cd /opt/insync/backend
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p /opt/insync/tools/models /opt/insync/tools/data/signs/nsl
cd /opt/insync/tools/models
[ -f hand_landmarker.task ] || curl -sL -o hand_landmarker.task https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
[ -f holistic_landmarker.task ] || curl -sL -o holistic_landmarker.task https://storage.googleapis.com/mediapipe-models/holistic_landmarker/holistic_landmarker/float16/latest/holistic_landmarker.task
sudo cp /opt/insync/deploy/insync.service /etc/systemd/system/insync.service
sudo sed "s/DOMAIN/$DOMAIN/" /opt/insync/deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now insync
sudo systemctl restart insync
sudo systemctl restart caddy
sleep 3
curl -s localhost:8000/health && echo
EOF
echo "== deployed: https://$DOMAIN  (health: https://$DOMAIN/health, signer UI: https://$DOMAIN/app)"
