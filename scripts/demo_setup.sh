#!/usr/bin/env bash
# Creates a demo tenant and an endpoint pointing at the mock receiver, then gives the receiver
# that endpoint's signing secret (like a real customer would put it in their server's config).
#
# Usage (stack must be running):  ./scripts/demo_setup.sh
# Writes the tenant's API key to .demo.env (gitignored) so other scripts and you can use it:
#   source .demo.env && curl -H "Authorization: Bearer $RELAY_API_KEY" localhost:8000/endpoints
set -euo pipefail
cd "$(dirname "$0")/.."

API=${API:-http://localhost:8000}
ADMIN_TOKEN=$(grep '^ADMIN_TOKEN=' .env | cut -d= -f2-)

api_key=$(curl -sf -X POST "$API/admin/tenants" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Demo tenant"}' | jq -r .api_key)

endpoint=$(curl -sf -X POST "$API/endpoints" \
  -H "Authorization: Bearer $api_key" -H 'Content-Type: application/json' \
  -d '{"url":"http://receiver:9000/webhook","event_types":["order.created","order.paid"]}')
endpoint_id=$(echo "$endpoint" | jq -r .id)
secret=$(echo "$endpoint" | jq -r .secret)

# Store the receiver's secret in .env (replacing any old one) so compose passes it in.
grep -v '^WEBHOOK_SECRET=' .env > .env.tmp && mv .env.tmp .env
echo "WEBHOOK_SECRET=$secret" >> .env
docker compose up -d --no-deps receiver >/dev/null 2>&1

printf 'RELAY_API_KEY=%s\nRELAY_ENDPOINT_ID=%s\n' "$api_key" "$endpoint_id" > .demo.env
echo "Demo tenant ready. Endpoint $endpoint_id -> http://receiver:9000/webhook"
echo "API key saved to .demo.env. Load it with:  source .demo.env"
