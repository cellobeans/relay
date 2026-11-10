#!/usr/bin/env bash
# Runs the k6 ingest test, waits for every delivery to finish, then reports delivery latency.
# Usage (stack running, receiver with FAIL_RATE=0):  ./loadtest/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .demo.env ] || ./scripts/demo_setup.sh
# shellcheck disable=SC1091
source .demo.env

RUN_ID="lt$(date +%s)"
mkdir -p loadtest/results
echo "Run id: $RUN_ID"

k6 run -e RELAY_API_KEY="$RELAY_API_KEY" -e RUN_ID="$RUN_ID" \
  --summary-export "loadtest/results/$RUN_ID-k6.json" loadtest/ingest.js

psql_relay() {
  docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' -- "$@"
}

echo "Waiting for the worker to finish this run's deliveries..."
for _ in $(seq 1 120); do
  pending=$(psql_relay -tAc "select count(*) from delivery_attempts d join events e on e.id = d.event_id
    where e.idempotency_key like '$RUN_ID-%' and d.status = 'pending'")
  [ "$pending" -eq 0 ] && break
  sleep 1
done
echo "Pending deliveries left: $pending"

echo
echo "Delivery latency:"
psql_relay -v run="$RUN_ID" -x < loadtest/delivery_latency.sql | tee "loadtest/results/$RUN_ID-delivery.txt"
