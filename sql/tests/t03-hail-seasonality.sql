-- Sanity check for q03-hail-seasonality.sql; zero rows = pass.
-- This checks source invariants only, not result accuracy.
SELECT event_id
FROM prancer.storm_events
WHERE event_type = 'Hail'
  AND state_abbr IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
  AND (EXTRACT(MONTH FROM begin_ts) < 1
       OR EXTRACT(MONTH FROM begin_ts) > 12);
