-- Sanity check for q01-flood-damage-by-year.sql; zero rows = pass.
-- This checks source invariants only, not result accuracy.
SELECT state_abbr, EXTRACT(YEAR FROM begin_ts) AS year
FROM prancer.storm_events
WHERE event_type IN ('Flood', 'Flash Flood')
  AND state_abbr IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
  AND begin_ts >= DATE '2015-01-01'
  AND begin_ts < DATE '2026-01-01'
  AND damage_property_usd < 0;
