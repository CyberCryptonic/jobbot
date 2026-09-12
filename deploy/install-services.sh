#!/bin/bash
# jobbot one-time service install. Run as:  sudo bash install-services.sh
# Does exactly four things, all reversible:
#   1. backs up the stock Caddyfile to /etc/caddy/Caddyfile.bak-stock
#   2. installs deploy/Caddyfile as /etc/caddy/Caddyfile + reloads caddy
#   3. installs systemd units jobbot-web + jobbot-chatd, with the unit's
#      YOURUSER/path placeholders replaced by the project owner and root
#   4. enables + starts both, then health-checks through caddy
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="$(stat -c %U "$PROJECT_ROOT")"
cd "$PROJECT_ROOT"

echo "== caddy =="
if [ ! -f /etc/caddy/Caddyfile.bak-stock ]; then
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-stock
fi
cp "$PROJECT_ROOT/deploy/Caddyfile" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl reload caddy
echo "Caddyfile installed and reloaded (stock config kept at Caddyfile.bak-stock)"

echo "== services =="
for unit in web chatd; do
    sed -e "s/YOURUSER/$OWNER/g" -e "s|/home/$OWNER/jobbot|$PROJECT_ROOT|g" \
        "$PROJECT_ROOT/deploy/$unit.service" > "/etc/systemd/system/jobbot-$unit.service"
done
systemctl daemon-reload
systemctl enable --now jobbot-web jobbot-chatd
sleep 2
systemctl is-active jobbot-web jobbot-chatd caddy

echo "== health check through caddy =="
curl -s -o /dev/null -w 'GET http://127.0.0.1/api/health -> %{http_code}\n' http://127.0.0.1/api/health
echo "install complete — dashboard on :80"
