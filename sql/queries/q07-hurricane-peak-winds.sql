-- Question: What is the strongest recorded track point
-- for each Atlantic storm in the Southeast coastal box?
-- Client use: Screen storms with peak winds near the target region.
-- Row unit: One hurricane/cyclone with a matching track point.
-- Exclusions / caveats: Atlantic tracks for 1980–2025;
-- approximate Southeast latitude/longitude box;
-- strongest track point selected, not necessarily landfall.
-- Test: sql/tests/t07-hurricane-peak-winds.sql

WITH ranked_tracks AS (
    SELECT
        s.storm_name,
        s.season_year,
        t.observed_at,
        t.lat,
        t.lon,
        t.max_wind_kt,
        ROW_NUMBER() OVER (
            PARTITION BY s.storm_id
            ORDER BY t.max_wind_kt DESC NULLS LAST, t.observed_at
        ) AS wind_rank
    FROM prancer.hurdat_storms AS s
    JOIN prancer.hurdat_tracks AS t
      ON s.storm_id = t.storm_id
    WHERE s.basin = 'AL'
      AND s.season_year BETWEEN 1980 AND 2025
      AND t.lat BETWEEN 24 AND 39.5
      AND t.lon BETWEEN -99 AND -74
)
SELECT
    storm_name,
    season_year,
    observed_at,
    lat,
    lon,
    max_wind_kt
FROM ranked_tracks
WHERE wind_rank = 1
ORDER BY max_wind_kt DESC NULLS LAST
LIMIT 25;
