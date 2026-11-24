# Runbook

Step-by-step guide for **Team Prancer's** Climate Risk Analytics and P&C Insurance Underwriting database pipeline. 

Team Prancer's PostgreSQL database is hosted on the Carnegie Mellon University course server (`mads_f26`) under the `prancer` schema. The system uses CMU Microsoft Entra authentication through the course-provided `course_db.py` module.

The commands below use Team Prancer’s original `prancer` schema. For the Team Vixen handoff, update the team name in the individual loaders and refresh scripts and change their schema-qualified SQL references, along with the corresponding schema setup and validation queries, to `vixen`. The new refresh controller does not accept `--team`.

---

## Connect

### 1. Set up Python environment

From the repository root, create and activate the virtual environment and install dependencies:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

In VS Code, open the Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`), run **Python: Select Interpreter**, and choose `.venv/bin/python`.

### 2. Configure credentials and test `course_db.py`

Export your CMU Andrew email (and `CENSUS_API_KEY` if running `--source census`):

```bash
export PGUSER="YOUR_ANDREW_ID@andrew.cmu.edu"
export CENSUS_API_KEY="YOUR_CENSUS_API_KEY"
```

Verify database connectivity from the repository root:

```bash
python src/course_db.py
```

**Expected output:** Confirms an active Entra-authenticated connection to `mads_f26`.

### 3. Connect from Python

Verify that `course_db.connect()` resolves to your target database and schema:

```bash
PYTHONPATH=src python -c "from course_db import connect; conn = connect(team='prancer'); print(conn.execute('SELECT current_database(), current_schema()').fetchone()); conn.close()"
```

**Expected output:**
```text
('mads_f26', 'prancer')
```

### 4. Connect from SQL (`psql` or VS Code PostgreSQL Extension)

Set your team write role and search path at the start of any direct SQL session:

```sql
SET ROLE prancer_write;
SET search_path = prancer, course, public;
```

> **Caution:** Do not re-run `sql/schema.sql` against an already populated schema unless performing an authorized full rebuild.

---

## Refresh the data

The ingestion pipelines are orchestrated by `src/refresh.py` from the repository root with `.venv` activated. Each individual refresh script handles its own data extraction, staging, merging, and database transactions. Temporary staging tables are dropped on commit, and a failed transaction rolls back without affecting previously committed data. GHCN commits historical data by year and API observations by batch.

The primary geographic scope covers **eight states**: Texas (`48`), Louisiana (`22`), Alabama (`01`), Georgia (`13`), Florida (`12`), South Carolina (`45`), North Carolina (`37`), and Virginia (`51`). GHCN observations, station metadata, Storm Events, NWS observations and alerts, and Census demographics are filtered to this region. HURDAT2 retains Atlantic hurricane tracks, including portions outside these states.

### Initial database setup and historical backfill

For a new, empty schema, create the database tables using `sql/schema.sql` with the appropriate team role and schema, then load the states reference table before the other data sources:

```bash
python src/run_schema.py # runs the schema.sql file
python src/load_states.py
```

The states loader reads `data/states.psv` and populates the eight target states. The course-provided `course.counties` table supplies county reference data.

Load historical GHCN observations and then current-year observations separately. Historical years are inclusive; adjust the range to the desired backfill coverage.

```bash
python src/refresh_ghcn.py --mode bulk --start-year 1996 --end-year 2025
python src/refresh_ghcn.py --mode api --start-date 2026-01-01
```

Load the other data sources:

```bash
python src/refresh_storms.py
python src/refresh_hurricanes.py
python src/refresh_nws.py
python src/refresh_nws_alerts.py
python src/refresh_census.py --acs-year 2024
```

The NWS loaders retrieve recent observations and alerts, not a multi-year historical backfill. Update the current-year GHCN start date and ACS release year as appropriate when initializing in a later year.

### Routine refreshes

After initialization, refresh all sources using:

```bash
python src/refresh.py --source all
```

Each source can also be refreshed independently according to the schedules below. The controller calls the individual refresh functions with their default settings. Historical backfill and source-specific options are handled by the individual scripts, not the controller.

### 1. GHCN-Daily Weather Observations — Daily

Downloads annual GHCN-Daily archives directly from NOAA NCEI for historical backfills and uses the NOAA daily-summaries API for current-year updates. Loads daily station temperature (`tmax`, `tmin`) and precipitation (`precip`) into `observations`. Station metadata are loaded into `stations`, and missing `county_fips` values are assigned using the nearest county centroid within the same state (an approximate geographic match).

```bash
python src/refresh.py --source ghcn
```

The routine API refresh retrieves the previous 14 days by default, restricted to the current calendar year and active/recent stations. To specify a different current-year window, call the individual script:

```bash
python src/refresh_ghcn.py --mode api --start-date 2026-01-01
```

Historical files already recorded as successfully loaded are skipped. To reprocess a specific historical year, use:

```bash
python src/refresh_ghcn.py --mode bulk --start-year 1996 --end-year 1996 --force
```

*Note: Re-running an unchanged window reports `0 inserted, 0 updated`. At the annual rollover, load the previous year's bulk archive to reconcile historical observations.*

### 2. National Weather Service (NWS) Surface Observations — Hourly

Fetches surface observations from `api.weather.gov` for ASOS (Automated Surface Observing System) stations within the eight target states. The NOAA ASOS metadata list currently identifies 219 stations. ASOS stations provide standardized, continuous weather measurements suitable for short-term severe-weather analysis. The loader requests the previous three days and retains the latest returned observation within each station-hour, with timestamps floored to the hour to avoid duplicate hourly records across refreshes.

```bash
python src/refresh.py --source nws
```

**Recorded output from the hourly loader:**
```text
Reduced 64,054 observations to 14,679 hourly observations
Fetched 14,679 observations
NWS refresh complete.
Rows staged: 14,679
Rows inserted: 14,679
Rows updated: 0
Rows unchanged: 0
```

*Note: Counts vary as live observations arrive. The API request cap may truncate the requested three-day window for some stations. Older stored observations are retained.*

### 3. NOAA Storm Events — Monthly

Checks the NOAA NCEI Storm Events directory for annual `.csv.gz` archives, processes historical and revised files, parses damage multipliers, and upserts severe-weather events within the target states into `storm_events`.

```bash
python src/refresh.py --source storms
```

*Note: Previously loaded unchanged files may be skipped; new or revised archives are processed by the individual refresh script.*

### 4. NHC HURDAT2 Atlantic Best Tracks — Seasonal

Downloads the NHC HURDAT2 Atlantic best-track archive and merges storm headers into `hurdat_storms` and track fixes into `hurdat_tracks`.

```bash
python src/refresh.py --source hurricanes
```

*Note: Atlantic tracks are not limited to the eight states because storms can develop and travel outside the region.*

### 5. U.S. Census ACS 5-Year County Demographics — Annual

Fetches ACS 5-year county estimates (population, median household income, median home value, and housing units) for the eight target states via the Census Data API into `county_demographics`. Requires `CENSUS_API_KEY`. The table stores one record per county and prevents older ACS releases from overwriting newer records.

```bash
python src/refresh.py --source census
```

The default ACS year is 2024. To load a different available release, use:

```bash
python src/refresh_census.py --acs-year 2024
```

Replace the year with the desired release when available.

### 6. National Weather Service (NWS) Alerts — Hourly

Fetches recent weather warnings, watches, and advisories from the NWS alerts API for the eight target states using a three-day lookback. Alerts affecting multiple states are deduplicated by `alert_id`. County FIPS arrays are derived from county-specific SAME codes when available. Previously stored alerts are retained after expiration.

```bash
python src/refresh.py --source nws_alerts
```

*Note: The observations and alerts loaders are separate refresh sources. The controller's `--source all` runs both.*

---

## Check the output

After each refresh, confirm schema tables, row counts, date coverage, and SQL test assertions.

### 1. Confirm all core tables exist

```sql
SELECT tablename
FROM pg_tables
WHERE schemaname = 'prancer'
ORDER BY tablename;
```

| Table | Contents |
|---|---|
| `states` | Target-state FIPS lookup (`8` rows) |
| `course.counties` | Course-provided county reference data and centroids |
| `county_demographics` | 2024 Census ACS 5-year county socioeconomic & housing exposure |
| `storm_events` | NOAA severe-weather events, casualties, and property/crop damage |
| `hurdat_storms` | NHC HURDAT2 tropical cyclone metadata (`1980`–present) |
| `hurdat_tracks` | 6-hourly synoptic, peak intensity, and landfall track fixes |
| `stations` | GHCN-Daily station metadata mapped to `state_fips` and `county_fips` |
| `observations` | Daily GHCN temperature and precipitation observations |
| `nws_observations` | Hourly NWS surface observations from selected ASOS stations |
| `nws_alerts` | Recent NWS weather warnings, watches, and advisories (retained historically) |
| `ingestion_runs` | Audit log of recorded ingestion runs |

### 2. Check row counts and newest dates loaded

```sql
SELECT 'storm_events' AS table_name, COUNT(*) AS row_count, MIN(begin_ts)::text AS earliest, MAX(begin_ts)::text AS latest FROM prancer.storm_events
UNION ALL
SELECT 'observations', COUNT(*), MIN(date)::text, MAX(date)::text FROM prancer.observations
UNION ALL
SELECT 'hurdat_tracks', COUNT(*), MIN(observed_at)::text, MAX(observed_at)::text FROM prancer.hurdat_tracks
UNION ALL
SELECT 'nws_observations', COUNT(*), MIN(observed_at)::text, MAX(observed_at)::text FROM prancer.nws_observations
UNION ALL
SELECT 'county_demographics', COUNT(*), MIN(acs_year)::text, MAX(acs_year)::text FROM prancer.county_demographics
UNION ALL
SELECT 'nws_alerts', COUNT(*), MIN(effective_at)::text, MAX(effective_at)::text FROM prancer.nws_alerts;
```

Counts depend on the historical backfill, upstream releases, and refresh date. The states table should contain eight records; Census should cover the counties and county equivalents in the target region.

### 3. Verify eight-state coverage

Confirm all eight target states are populated in `storm_events`:

```sql
SELECT
    s.state_abbr,
    e.state_fips,
    COUNT(*) AS total_events,
    MAX(e.begin_ts)::date AS latest_event
FROM prancer.storm_events AS e
JOIN prancer.states AS s USING (state_fips)
WHERE e.state_fips IN ('48', '22', '01', '13', '12', '45', '37', '51')
GROUP BY s.state_abbr, e.state_fips
ORDER BY e.state_fips;
```

### 4. Audit `ingestion_runs`

```sql
SELECT run_id, started_at, source, rows_staged, rows_inserted, rows_updated
FROM prancer.ingestion_runs
ORDER BY run_id DESC
LIMIT 10;
```

*Normal behavior:* Ingestion records reflect completed loads. Historical sources may log individual files, and skipped files need not produce a new record. Rerunning unchanged data should produce zero inserts and updates; live sources may receive new data between runs.

### 5. Execute client SQL queries (`sql/queries/`) and validation tests (`sql/tests/`)

Run the eight validation test scripts (`t01`–`t08`) against your schema:

```bash
for t in sql/tests/t0[1-8]*.sql; do
    echo "=== Running $t ==="
    psql -d mads_f26 -v ON_ERROR_STOP=1 -c "SET search_path = prancer, course, public;" -f "$t"
done
```

**What normal looks like:** **Every passing test returns `0` rows.** Any returned rows indicate data anomalies or broken invariants requiring investigation. (Note: `t00` database-level validation scripts are separate and require further review.)

**Client queries in `sql/queries/q01`–`q08` (row counts vary with scope and data coverage):**

| Query | Analytical Focus |
|---|---|
| `Q01` — Flood damage by year | Annual flood property loss trajectory |
| `Q02` — Flood frequency vs. severity | State-level frequency vs. severity decomposition |
| `Q03` — Hail seasonality | Seasonal hail exposure across target regions |
| `Q04` — Billion-dollar episodes | Catastrophic multi-billion-dollar storm episodes |
| `Q05` — Fatalities vs. damage | Under-counted property damage relative to mortality |
| `Q06` — County damage per capita | Per-capita and housing-adjusted county storm losses |
| `Q07` — Hurricane peak winds | Maximum sustained wind intensity by cyclone |
| `Q08` — Hurricane station proximity | Coastal station observations near cyclone tracks |


---

## When something fails

| What you see | What it means | What to do |
|---|---|---|
| `ModuleNotFoundError: No module named 'course_db'` | Script was invoked outside the repo root or `.venv` is inactive | `cd` to the repository root, run `source .venv/bin/activate`, and verify `src/course_db.py` exists |
| CMU Entra authentication failure | Expired SSO token or missing `PGUSER` | Run `export PGUSER="YOUR_ANDREW_ID@andrew.cmu.edu"`, complete CMU Microsoft Entra sign-in, and retry |
| `Missing CENSUS_API_KEY environment variable.` | `--source census` ran without `CENSUS_API_KEY` set | Run `export CENSUS_API_KEY="your_key"` and re-execute |
| `Validation failed; nothing was loaded: negative precipitation` or `tmax below tmin` | Upstream NOAA observations contained invalid physical values | Transaction rolled back automatically; inspect the source data, log in `docs/technical-spec.md`, and rerun |
| `HURDAT2 integrity error on <storm_id>: expected <X> pts, saw <Y>` | NHC's `hurdat2` archive had a truncated storm record or partial download | Wait 1–2 minutes and rerun `--source hurricanes`; no partial rows were committed |
| `requests.exceptions.HTTPError` or `ReadTimeout` (NWS / NOAA / Census) | Upstream federal API is temporarily throttled or unreachable | Wait 2–5 minutes and retry; check upstream availability |
| `relation "..." does not exist` | Wrong schema on `search_path` or table not yet created | Run `SET search_path = prancer, course, public;` and check `pg_tables` |
| `column does not exist` | Query and table definitions differ | Compare the SQL against current column definitions in `sql/schema.sql` |
| `duplicate key value violates unique constraint` | Staging rows conflicted with an existing primary/unique key | Inspect `ON CONFLICT` target columns in the relevant refresh script against `sql/schema.sql` |
| `0 rows inserted, 0 updated` | Requested date window is already loaded and unchanged | Confirm `MAX(begin_ts)` / `MAX(date)` in target table; no action needed if current |


---

## Reports

### State-Level Flood Property Damage Growth (Frequency vs. Severity)

* **Client question:** Which states saw the biggest rise in flood property damage, and is that rise driven by how often floods happen (frequency) or how bad they are (severity)?
* **Built by:** `src/report.py`, which runs a parameterized query against `storm_events` (`event_type ILIKE '%Flood%'`) joined with `states` to compare event frequency (`Base_Cnt` vs. `Rec_Cnt`) and mean per-event severity (`Base_Avg($M)` vs. `Rec_Avg($M)`) across two 15-year windows (`1996-01-01`–`2011-01-01` vs. `2011-01-01`–`2026-09-01`).
* **Regenerate Command:**
  ```bash
  python src/report.py --team prancer
  ```
  *To filter to a single state (2-letter postal code or 2-digit FIPS) or customize comparison windows:*
  ```bash
  python src/report.py --team prancer --state TX --limit 10
  ```
* **When new data arrive:** NOAA Storm Events (`--source storms`) updates monthly. Because `src/report.py` binds `search_path` dynamically via `--team` and queries base tables directly, rerunning the command immediately incorporates newly loaded events with no intermediate views to rebuild.
* **Check after each refresh:** Review the top-ranked states and confirm that the results reflect the current data and geographic scope.

---

## Recover

If a refresh fails or data becomes corrupted, follow these steps to restore a clean database state:

### 1. Identify the failing source

Read the terminal error message to determine whether the failure occurred during HTTP download, CSV/JSON parsing, staging validation, or `ON CONFLICT` upserts.

### 2. Verify the database connection

```bash
python src/course_db.py
```

Confirm `mads_f26` is reachable and your target schema tables are intact.

### 3. Check for partial changes

The individual loaders use `with conn.transaction():` and temporary staging tables. If an exception is raised, PostgreSQL rolls back the failing transaction. Earlier committed years, batches, or sources remain untouched. Verify via the affected table's row count and `ingestion_runs`.

### 4. Resolve the root cause

* **Invalid source records:** Inspect the offending records in the upstream feed or downloaded archive, adjust cleaning/validation logic if needed, and document the decision under Known Issues in `docs/technical-spec.md`.
* **Schema mismatch:** Compare live table columns against `sql/schema.sql`.
* **API or auth failure:** Verify network access, `CENSUS_API_KEY`, or CMU Entra sign-in (`PGUSER`).

### 5. Retry the affected source

After resolving the issue, rerun only the failed source, for example:

```bash
python src/refresh.py --source ghcn
```

For a missed current-year GHCN window, specify the start date directly in `refresh_ghcn.py`. For a historical file that needs to be reprocessed, use bulk mode with `--force` as described above.

### 6. Resume routine refreshes

```bash
python src/refresh.py --source all
```

If rebuilding an entire schema from scratch after authorization, follow the initial database setup and historical backfill instructions above. Ensure ingestion history is consistent with the rebuilt tables so historical files are not incorrectly skipped.

### 7. Verify recovery

Check row counts, date coverage, `ingestion_runs`, `sql/tests/t01`–`t08`, and `python src/report.py --team prancer`. Re-running unchanged data should yield `0 inserted, 0 updated` with no duplicate records; live sources may have new observations or alerts.

> **Caution:** Do not drop populated tables or rebuild the database without authorization.

---

## Who owns what

### Builders — Team Prancer

Team Prancer designed and built the Climate Risk Analytics system and is responsible for its original database schema, ingestion pipelines, client queries, validation tests, and handoff documentation.

| Component | Original Responsibility (Team Prancer) | Primary Files & Tables |
|---|---|---|
| **Database Architecture & Core Ingestion Pipeline** | Ainika Hou | `sql/schema.sql`, `src/refresh.py`, `states`, `counties`, `stations`, `observations`, `nws_observations`, `county_demographics`, `ingestion_runs` |
| **NOAA Storm Events & Hurricane Ingestion** | Matt Mellors | `src/refresh_storms.py`, `src/refresh_hurricanes.py`, `storm_events`, `hurdat_storms`, `hurdat_tracks` |
| **Client SQL Queries & Validation Tests** | Bruck Setu | `sql/queries/q01`–`q08`, `sql/tests/t01`–`t08` |
| **Client CLI Report, Integration & Documentation** | Team Prancer collectively | `src/report.py`, `README.md`, `docs/technical-spec.md`, `docs/runbook.md` |

### Receivers — Team Vixen

**Team Vixen** assumes operational ownership of the Climate Risk Analytics system during the **November 23** knowledge-transfer session.

* **Post-handoff responsibilities:** Running scheduled refreshes after configuring the `vixen` schema, monitoring data quality, executing validation tests, and investigating upstream feed failures.
* **Design support & documentation:** Team Prancer will walk through architectural choices and known limitations during the November 23 handoff; Team Vixen should use `README.md`, `docs/technical-spec.md`, and this `docs/runbook.md` as the primary operational reference.
