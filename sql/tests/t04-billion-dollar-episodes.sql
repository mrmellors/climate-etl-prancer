-- Sanity check for q04-billion-dollar-episodes.sql; zero rows = pass.
-- This checks source invariants only, not result accuracy.
SELECT episode_id
FROM prancer.storm_events
WHERE episode_id IS NOT NULL
  AND damage_property_usd < 0;
