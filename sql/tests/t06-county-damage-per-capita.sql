-- Sanity check for q06-county-damage-per-capita.sql; zero rows = pass.
-- This checks source invariants only, not result accuracy.
SELECT county_fips
FROM prancer.county_demographics
WHERE population < 0;
