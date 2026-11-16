-- Schema: creates every table, key, and constraint from scratch.
--
-- What goes here: one CREATE TABLE per table, in an order that works (referenced tables
-- first), each with a comment giving its row unit. Running this file on an empty team
-- schema must succeed. Replace the example with your own tables.
--
-- Run it as your team, so the tables belong to the team and survive the handoff:

SET ROLE prancer_write;
SET search_path = prancer, course, public;

-- Example: the shared course tables, as a team would write them.

-- Row unit: one weather station.
CREATE TABLE stations (
  station_id TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  state      CHAR(2) CHECK (state ~ '^[A-Z]{2}$'),
  lat        DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lon        DOUBLE PRECISION NOT NULL CHECK (lon BETWEEN -180 AND 180),
  elevation  NUMERIC(7, 2)                       -- meters
);

-- Row unit: one station on one date.
CREATE TABLE observations (
  obs_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  station_id TEXT NOT NULL REFERENCES stations (station_id),
  date       DATE NOT NULL,
  tmax       NUMERIC,                            -- degrees C
  tmin       NUMERIC,                            -- degrees C
  precip     NUMERIC CHECK (precip >= 0),        -- millimeters
  CHECK (tmax IS NULL OR tmin IS NULL OR tmax >= tmin),
  UNIQUE (station_id, date)
);

-- Row unit: one run of src/refresh.py.
CREATE TABLE ingestion_runs (
    run_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source        TEXT NOT NULL,
    filename      TEXT,
    status        TEXT NOT NULL DEFAULT 'success',
    rows_staged   INTEGER NOT NULL,
    rows_inserted INTEGER NOT NULL,
    rows_updated  INTEGER NOT NULL
);

CREATE TABLE prancer.storm_events (
    event_id BIGINT PRIMARY KEY,
    episode_id BIGINT,

    state TEXT,
    state_fips CHAR(2),
    event_type TEXT,

    cz_type CHAR(1),
    cz_fips VARCHAR(3),
    cz_name TEXT,
    county_fips CHAR(5),

    begin_date_time TIMESTAMP,
    end_date_time TIMESTAMP,
    cz_timezone TEXT,

    damage_property NUMERIC(16, 2),
    damage_crops NUMERIC(16, 2),

    deaths_direct INTEGER,
    deaths_indirect INTEGER,
    injuries_direct INTEGER,
    injuries_indirect INTEGER,

    begin_lat DOUBLE PRECISION,
    begin_lon DOUBLE PRECISION,
    end_lat DOUBLE PRECISION,
    end_lon DOUBLE PRECISION,

    magnitude NUMERIC,
    magnitude_type TEXT
);
