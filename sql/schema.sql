-- Schema: creates every table, key, and constraint from scratch for
-- Climate Risk Analytics & P&C Insurance Underwriting project.
--
-- Run as team prancer so tables belong to the team and survive the handoff:
SET ROLE prancer_write;
SET search_path = prancer, course, public;


-- Row unit: one US state, district, or territory
CREATE TABLE prancer.states (
    state_fips CHAR(2) PRIMARY KEY,
    state_abbr CHAR(2) UNIQUE NOT NULL,
    state_name TEXT UNIQUE NOT NULL,

    CONSTRAINT valid_state_fips
        CHECK (state_fips ~ '^[0-9]{2}$'),

    CONSTRAINT valid_state_abbr
        CHECK (state_abbr ~ '^[A-Z]{2}$')
);


-- ============================================================================
-- 1. CENSUS ACS 5-YEAR COUNTY DEMOGRAPHICS (Annual schedule)
-- ============================================================================

-- Row unit: one U.S. county from the 2024 Census ACS 5-year estimates.
CREATE TABLE county_demographics (
  county_fips       CHAR(5) PRIMARY KEY CHECK (county_fips ~ '^[0-9]{5}$'),
  county_name       TEXT NOT NULL,
  acs_year          INTEGER NOT NULL CHECK (acs_year BETWEEN 2009 AND 2030),
  population        INTEGER CHECK (population >= 0),             -- people
  median_income     NUMERIC(12, 2) CHECK (median_income >= 0),   -- USD
  median_home_value NUMERIC(14, 2) CHECK (median_home_value >= 0), -- USD
  housing_units     INTEGER CHECK (housing_units >= 0)           -- housing units
);

-- ============================================================================
-- 2. NOAA STORM EVENTS (Monthly schedule)
-- ============================================================================

-- Row unit: one NOAA storm event record in one county or forecast zone.
CREATE TABLE storm_events (
  event_id            BIGINT PRIMARY KEY,
  episode_id          BIGINT,
  state_fips          CHAR(2) REFERENCES prancer.states(state_fips),
  noaa_region         TEXT,                                                -- ocean regions (State_FIPS Will be NULL)
  cz_type             CHAR(1) NOT NULL, -- C=County, Z=Zone, M=Marine, 5 = Desert (if not error)
  cz_fips             VARCHAR(3) NOT NULL,
  cz_name             TEXT,
  cz_timezone         TEXT,
  county_fips         CHAR(5) CHECK (county_fips IS NULL OR county_fips ~ '^[0-9]{5}$'),
  event_type          TEXT NOT NULL,
  begin_ts            TIMESTAMPTZ NOT NULL,                      -- UTC
  end_ts              TIMESTAMPTZ,                               -- UTC
  injuries_direct     INTEGER NOT NULL DEFAULT 0 CHECK (injuries_direct >= 0),   -- people
  injuries_indirect   INTEGER NOT NULL DEFAULT 0 CHECK (injuries_indirect >= 0), -- people
  deaths_direct       INTEGER NOT NULL DEFAULT 0 CHECK (deaths_direct >= 0),     -- people
  deaths_indirect     INTEGER NOT NULL DEFAULT 0 CHECK (deaths_indirect >= 0),   -- people
  damage_property_usd NUMERIC(16, 2) CHECK (damage_property_usd >= 0),           -- USD
  damage_crops_usd    NUMERIC(16, 2) CHECK (damage_crops_usd >= 0),              -- USD
  magnitude           NUMERIC,                                                   -- inches (hail) or knots (wind)
  magnitude_type      TEXT,
  begin_lat           DOUBLE PRECISION CHECK (begin_lat BETWEEN -90 AND 90),     -- decimal degrees
  begin_lon           DOUBLE PRECISION CHECK (begin_lon BETWEEN -180 AND 180),   -- decimal degrees
  end_lat             DOUBLE PRECISION CHECK (end_lat BETWEEN -90 AND 90),       -- decimal degrees
  end_lon             DOUBLE PRECISION CHECK (end_lon BETWEEN -180 AND 180)     -- decimal degrees
);

CREATE INDEX idx_storm_events_episode ON storm_events (episode_id);
CREATE INDEX idx_storm_events_county  ON storm_events (county_fips);
CREATE INDEX idx_storm_events_type_ts ON storm_events (event_type, begin_ts);

-- ============================================================================
-- 3. HURDAT2 ATLANTIC HURRICANE BEST TRACKS (Seasonal schedule)
-- ============================================================================

-- Row unit: one Atlantic tropical or subtropical cyclone in NHC HURDAT2.
CREATE TABLE hurdat_storms (
  storm_id         TEXT PRIMARY KEY CHECK (storm_id ~ '^(AL|EP|CP)[0-9]{6}$'),
  storm_name       TEXT NOT NULL,
  basin            CHAR(2) NOT NULL CHECK (basin IN ('AL', 'EP', 'CP')),
  cyclone_number   INTEGER NOT NULL CHECK (cyclone_number > 0),
  season_year      INTEGER NOT NULL CHECK (season_year BETWEEN 1851 AND 2030),
  num_track_points INTEGER NOT NULL CHECK (num_track_points > 0) -- count
);

-- Row unit: one 6-hourly or asynoptic landfall/peak best-track fix for a cyclone.
CREATE TABLE hurdat_tracks (
  track_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  storm_id          TEXT NOT NULL REFERENCES hurdat_storms (storm_id) ON DELETE CASCADE,
  observed_at       TIMESTAMPTZ NOT NULL,                      -- UTC
  record_identifier CHAR(1) NOT NULL DEFAULT 'R',              -- L=landfall, I=peak, R=regular synoptic
  system_status     TEXT NOT NULL,                             -- HU, TS, TD, EX, SD, SS, LO, WV, DB
  lat               DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),   -- decimal degrees
  lon               DOUBLE PRECISION NOT NULL CHECK (lon BETWEEN -180 AND 180), -- decimal degrees
  max_wind_kt       INTEGER CHECK (max_wind_kt >= 0),          -- knots
  min_pressure_mb   INTEGER CHECK (min_pressure_mb > 0),       -- millibars
  UNIQUE (storm_id, observed_at, record_identifier)
);

CREATE INDEX idx_hurdat_tracks_storm   ON hurdat_tracks (storm_id);
CREATE INDEX idx_hurdat_tracks_lat_lon ON hurdat_tracks (lat, lon);

-- ============================================================================
-- 4. GHCN-DAILY WEATHER STATIONS & OBSERVATIONS (Daily schedule)
-- ============================================================================

-- Row unit: one GHCN-Daily weather station.
CREATE TABLE stations (
  station_id  TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  state_fips CHAR(2) REFERENCES prancer.states(state_fips),
  county_fips CHAR(5) CHECK (county_fips IS NULL OR county_fips ~ '^[0-9]{5}$'),
  lat         DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),   -- decimal degrees
  lon         DOUBLE PRECISION NOT NULL CHECK (lon BETWEEN -180 AND 180), -- decimal degrees
  elevation   NUMERIC(7, 2)                                               -- meters
);

-- Row unit: one GHCN-Daily station on one observation date.
CREATE TABLE observations (
  obs_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  station_id TEXT NOT NULL REFERENCES stations (station_id),
  date       DATE NOT NULL,
  tmax       NUMERIC,                                          -- degrees C
  tmin       NUMERIC,                                          -- degrees C
  precip     NUMERIC CHECK (precip >= 0),                      -- millimeters
  CHECK (tmax IS NULL OR tmin IS NULL OR tmax >= tmin),
  UNIQUE (station_id, date)
);

-- ============================================================================
-- 5. NWS LIVE OBSERVATIONS & ACTIVE ALERTS (Hourly / Live schedule)
-- ============================================================================

-- Row unit: one automated surface observation timestamp at an NWS station.
CREATE TABLE nws_observations (
  station_id              TEXT NOT NULL,
  observed_at             TIMESTAMPTZ NOT NULL,                      -- UTC
  lat                     DOUBLE PRECISION CHECK (lat BETWEEN -90 AND 90),   -- decimal degrees
  lon                     DOUBLE PRECISION CHECK (lon BETWEEN -180 AND 180), -- decimal degrees
  temperature_c           NUMERIC,                                           -- degrees C
  dewpoint_c              NUMERIC,                                           -- degrees C
  wind_speed_kmh          NUMERIC CHECK (wind_speed_kmh >= 0),               -- km/h
  wind_gust_kmh           NUMERIC CHECK (wind_gust_kmh >= 0),                -- km/h
  barometric_pressure_pa  NUMERIC CHECK (barometric_pressure_pa > 0),        -- Pascals
  relative_humidity_pct   NUMERIC CHECK (relative_humidity_pct BETWEEN 0 AND 100), -- percent
  text_description        TEXT,
  PRIMARY KEY (station_id, observed_at)
);

-- Row unit: one active NWS weather alert / warning.
CREATE TABLE nws_alerts (
  alert_id     TEXT PRIMARY KEY,
  event        TEXT NOT NULL,
  severity     TEXT,
  certainty    TEXT,
  urgency      TEXT,
  area_desc    TEXT,
  county_fips  CHAR(5)[],                                      -- array of 5-digit county FIPS codes
  effective_at TIMESTAMPTZ,                                    -- UTC
  expires_at   TIMESTAMPTZ,                                    -- UTC
  headline     TEXT
);

-- ============================================================================
-- 6. INGESTION AUDIT LOG
-- ============================================================================

-- Row unit: one execution of src/refresh.py for one data source.
CREATE TABLE ingestion_runs (
    run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT NOT NULL,
    filename TEXT,
    status TEXT NOT NULL DEFAULT 'success'
        CHECK (status IN ('success', 'failed')),
    rows_staged INTEGER NOT NULL DEFAULT 0 CHECK (rows_staged >= 0),
    rows_inserted INTEGER NOT NULL DEFAULT 0 CHECK (rows_inserted >= 0),
    rows_updated INTEGER NOT NULL DEFAULT 0 CHECK (rows_updated >= 0)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_source_filename
ON prancer.ingestion_runs (source, filename)
WHERE status = 'success';