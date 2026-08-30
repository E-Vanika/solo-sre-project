cat > scripts/rollback.sh << 'EOF'
#!/usr/bin/env bash
# Manual rollback - run on the VM: ./rollback.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .last_good_tag ]]; then
  echo "No .last_good_tag recorded. Check 'docker images' and set IMAGE_TAG manually in .env."
  exit 1
fi

PREV=$(cat .last_good_tag)
echo "Rolling back to image tag: $PREV"
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$PREV/" .env
docker compose pull app app-2 greeting-service
docker compose up -d --no-deps app app-2 greeting-service
sleep 5
curl -fsS http://localhost/health && echo "Rollback OK"
EOF
chmod +x scripts/rollback.sh