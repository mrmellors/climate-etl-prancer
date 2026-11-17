-- Sanity check for q07-hurricane-peak-winds.sql; zero rows = pass.
-- This checks source invariants only, not result accuracy.
SELECT track_id
FROM prancer.hurdat_tracks
WHERE max_wind_kt < 0;
