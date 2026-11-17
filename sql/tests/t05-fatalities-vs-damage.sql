-- Sanity check for q05-fatalities-vs-damage.sql; zero rows = pass.
-- This checks source invariants only, not result accuracy.
SELECT event_id
FROM prancer.storm_events
WHERE deaths_direct < 0 OR deaths_indirect < 0;
