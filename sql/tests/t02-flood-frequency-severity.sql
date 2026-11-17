-- Sanity check for q02-flood-frequency-severity.sql; zero rows = pass.
-- This checks source invariants only, not result accuracy.
SELECT event_id
FROM prancer.storm_events
WHERE event_type IN ('Flood', 'Flash Flood')
  AND state_abbr IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
  AND damage_property_usd < 0;
