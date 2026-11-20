-- This lets you drop the table once we are done testing stuff
-- Can then try and reload more data possibly
SET ROLE prancer_write;
SET search_path = prancer, course, public;

DROP TABLE IF EXISTS prancer.ingestion_runs

SELECT
    pg_size_pretty(pg_relation_size('prancer.hurdat_storms')) AS table_size,
    pg_size_pretty(pg_indexes_size('prancer.hurdat_storms')) AS index_size,
    pg_size_pretty(pg_total_relation_size('prancer.hurdat_storms')) AS total_size;

SELECT COUNT(*) FROM prancer.hurdat_storms;
SELECT COUNT(*) FROM prancer.hurdat_tracks;


SELECT
    pg_size_pretty(pg_relation_size('prancer.hurdat_tracks')) AS table_size,
    pg_size_pretty(pg_indexes_size('prancer.hurdat_tracks')) AS index_size,
    pg_size_pretty(pg_total_relation_size('prancer.hurdat_tracks')) AS total_size;