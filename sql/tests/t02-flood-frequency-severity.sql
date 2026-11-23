-- Sanity check for Q02; zero rows = pass.
-- Checks for negative flood property damage.

SELECT event_id
FROM prancer.storm_events
WHERE event_type IN ('Flood', 'Flash Flood')
  AND state_fips IN ('48', '22', '01', '13', '12', '45', '37', '51')
  AND damage_property_usd < 0;