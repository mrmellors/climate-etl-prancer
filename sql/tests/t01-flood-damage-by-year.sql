-- Sanity check for Q01; zero rows = pass.
-- Checks for negative property damage.

SELECT
    state_fips,
    EXTRACT(YEAR FROM begin_ts) AS year
FROM prancer.storm_events
WHERE event_type IN ('Flood', 'Flash Flood')
  AND state_fips IN ('48', '22', '01', '13', '12', '45', '37', '51')
  AND begin_ts >= DATE '2015-01-01'
  AND begin_ts < DATE '2026-01-01'
  AND damage_property_usd < 0;