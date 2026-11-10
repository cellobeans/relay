// k6 load test for POST /events.
// Run via loadtest/run.sh (it creates the tenant, then measures delivery latency afterwards).
//
// Ramps from 0 to 50 virtual users, each sending events as fast as it can (no pauses), so the
// result shows how much ingestion one API process sustains and how latency behaves under load.
import http from 'k6/http';
import { check } from 'k6';

const API = __ENV.API || 'http://localhost:8000';
const API_KEY = __ENV.RELAY_API_KEY;
const RUN_ID = __ENV.RUN_ID || `run${Date.now()}`;

export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '15s', target: 10 },
        { duration: '30s', target: 25 },
        { duration: '30s', target: 50 },
        { duration: '15s', target: 0 },
      ],
      gracefulRampDown: '5s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'], // under 1% errors
    'http_req_duration{name:ingest}': ['p(95)<500'], // p95 under 500 ms
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
  if (!API_KEY) throw new Error('RELAY_API_KEY is not set (run loadtest/run.sh)');
}

export default function () {
  const res = http.post(
    `${API}/events`,
    JSON.stringify({ type: 'order.created', payload: { vu: __VU, iteration: __ITER } }),
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${API_KEY}`,
        // Unique per request, and prefixed with the run id so delivery latency can be
        // measured for exactly this run's events afterwards.
        'Idempotency-Key': `${RUN_ID}-${__VU}-${__ITER}`,
      },
      tags: { name: 'ingest' },
    },
  );
  check(res, { 'status is 201': (r) => r.status === 201 });
}
