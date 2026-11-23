-- Sanity check for Q03; zero rows = pass.
-- Checks whether extracted hail months are valid.

SELECT event_id
FROM prancer.storm_events
WHERE event_type = 'Hail'
  AND state_fips IN ('48', '22', '01', '13', '12', '45', '37', '51')
  AND (
      EXTRACT(MONTH FROM begin_ts) < 1
      OR EXTRACT(MONTH FROM begin_ts) > 12
  );