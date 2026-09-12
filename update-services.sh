#!/bin/bash
# Re-install unit files from the repo and restart both services.
# Run as:  sudo bash update-services.sh
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
OWNER="$(stat -c %U "$PROJECT_ROOT")"
cd "$PROJECT_ROOT"
for unit in web chatd; do
    sed -e "s/YOURUSER/$OWNER/g" -e "s|/home/$OWNER/jobbot|$PROJECT_ROOT|g" \
        "deploy/$unit.service" > "/etc/systemd/system/jobbot-$unit.service"
done
systemctl daemon-reload
systemctl restart jobbot-web jobbot-chatd
sleep 2
systemctl is-active jobbot-web jobbot-chatd
curl -s -o /dev/null -w 'dashboard health -> %{http_code}\n' http://127.0.0.1/api/health
