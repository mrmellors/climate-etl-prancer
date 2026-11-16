-- Testing to see if the schema created the table and that the load_csv worked
SELECT *
FROM prancer.storm_events
WHERE end_date_time >= '2026-01-01'
  AND end_date_time < '2027-01-01'
LIMIT 10;

-- This lets you drop the table once we are done testing stuff
-- Can then try and reload more data possibly
SET ROLE prancer_write;
SET search_path = prancer, course, public;

DROP TABLE IF EXISTS prancer.storm_events;

DROP TABLE IF EXISTS prancer.ingestion_runs

SELECT
    pg_size_pretty(pg_relation_size('prancer.storm_events')) AS table_size,
    pg_size_pretty(pg_indexes_size('prancer.storm_events')) AS index_size,
    pg_size_pretty(pg_total_relation_size('prancer.storm_events')) AS total_size;