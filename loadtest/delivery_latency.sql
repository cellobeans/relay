-- Delivery latency for one load-test run, computed from delivery_attempts.
-- Usage: psql -v run=<RUN_ID> -f loadtest/delivery_latency.sql
--
-- end_to_end = event accepted by the API  ->  receiver answered 2xx
--              (includes time waiting in the Redis queue behind other deliveries)
-- http       = just the worker's HTTP call to the receiver (latency_ms)

with run_attempts as (
    select d.*, e.created_at as event_created_at
    from delivery_attempts d
    join events e on e.id = d.event_id
    where e.idempotency_key like :'run' || '-%'
)
select
    (select count(*) from run_attempts) as attempts,
    (select count(*) from run_attempts where status = 'succeeded') as succeeded,
    (select count(*) from run_attempts where status <> 'succeeded') as not_succeeded,
    round(percentile_cont(0.50) within group (order by e2e_ms)) as e2e_p50_ms,
    round(percentile_cont(0.95) within group (order by e2e_ms)) as e2e_p95_ms,
    round(percentile_cont(0.99) within group (order by e2e_ms)) as e2e_p99_ms,
    round(max(e2e_ms)) as e2e_max_ms,
    round(percentile_cont(0.95) within group (order by latency_ms)) as http_p95_ms
from (
    select
        extract(epoch from completed_at - event_created_at) * 1000 as e2e_ms,
        latency_ms
    from run_attempts
    where status = 'succeeded'
) t;
