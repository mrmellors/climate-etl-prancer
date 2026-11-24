# Climate Risk Analytics & P&C Insurance Underwriting · Team Prancer

## What this system is for

This PostgreSQL system supports a property and casualty (P&C) insurer's underwriting and exposure team. It helps evaluate weather-related insurance risks, inform policy pricing, allocate claims adjusters during severe-weather seasons, and identify weather events associated with significant property damage.

The project's primary geographic scope is the **Southeast coastal United States**, covering six states: **Texas, Louisiana, Florida, Georgia, South Carolina, and North Carolina**, rather than the entire continental United States.

The system integrates the following data sources:

- **NOAA Storm Events (1996–2026):** Historical severe-weather events, including flood damage, hail, fatalities, and property losses.
- **NHC HURDAT2 (1980–2025):** Atlantic hurricane tracks, locations, and maximum recorded wind speeds.
- **GHCN-Daily:** Daily weather-station observations, including precipitation and temperature.
- **National Weather Service (NWS):** Current weather observations and alerts.
- **2024 Census ACS 5-Year Estimates:** County-level population, median income, and housing information.

The datasets have different historical coverage and update schedules. County FIPS codes support geographic joins between storm events and Census demographics, while latitude and longitude support spatial analyses involving hurricane tracks and weather stations.

Note: NWS weather observations are restricted to 219 Automated Surface Observing System (ASOS) stations across our eight target states. ASOS stations were selected because they provide reliable, standardized, and continuous weather measurements, making them particularly useful for monitoring short-term weather conditions and severe weather events. To manage database storage while maintaining geographic coverage, the pipeline retrieves observations from the previous three days and retains the most recent observation within each hour for each station. This complements the broader historical coverage provided by GHCN-Daily while limiting unnecessary high-frequency data storage.

The system supports eight client-facing SQL queries investigating flood damage trends, event frequency versus severity, hail seasonality, billion-dollar storm episodes, fatalities relative to property damage, county damage per capita, hurricane wind intensity, and weather-station proximity to hurricanes.

The system does not include proprietary insurance claims, Zillow typical home values, or satellite building-damage imagery. Analyses are limited to the available records and geographic coverage of each source.

## Start here

These instructions are intended for Team Vixen, which will take over the Climate Risk Analytics system during the November 23 knowledge transfer.

### 1. Set up the Python environment

From the repository's root directory, run:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

In VS Code, select the `.venv` Python interpreter.

### 2. Connect to the course database

The system connects to PostgreSQL using CMU Microsoft Entra authentication through the course-provided `course_db` module. No database password or token should be stored in the repository.

Ensure the course-provided `course_db.py` is available in the `src/` directory.

If necessary, configure your CMU username in the terminal:

```bash
export PGUSER="YOUR_ANDREW_ID@andrew.cmu.edu"
```

Test the connection:

```bash
python src/course_db.py
```

A successful connection should identify the course database (`mads_f26`).

All Team Prancer database operations should use:

```python
from course_db import connect

conn = connect(team="prancer")
```

This connects using the team's database role and schema.

### 3. Verify the database tables

Connect to PostgreSQL and run:

```sql
SELECT tablename
FROM pg_tables
WHERE schemaname = 'prancer'
ORDER BY tablename;
```

The primary tables include:

| Table | Description |
|---|---|
| `storm_events` | NOAA severe-weather events, damage, and casualties |
| `hurdat_storms` | Atlantic hurricane identifiers and metadata |
| `hurdat_tracks` | Hurricane track positions and wind observations |
| `stations` | GHCN weather-station information |
| `observations` | Daily weather observations |
| `nws_observations` | NWS weather-station observations |
| `nws_alerts` | NWS weather alerts |
| `county_demographics` | Census county demographic and housing estimates |
| `ingestion_runs` | Refresh history and ingestion statistics |


### 4. Run a safe refresh

Each data source can be refreshed independently because the sources update on different schedules. The refresh controller uses the default settings for each source, while historical backfills and custom date ranges are handled by the individual refresh scripts.

To refresh recent GHCN observations:

```bash
python src/refresh.py --source ghcn
```

This refresh retrieves the previous 14 days of current-year GHCN observations by default. A successful run reports the records processed and ends with:

```text
Refresh complete!
```

To refresh GHCN observations starting from a specific date:

```bash
python src/refresh_ghcn.py --mode api --start-date 2026-01-01
```

To load historical GHCN observations:

```bash
python src/refresh_ghcn.py --mode bulk --start-year 1996 --end-year 2025
```

Additional refresh commands are available for each source:

```bash
python src/refresh.py --source storms
python src/refresh.py --source hurricanes
python src/refresh.py --source nws
python src/refresh.py --source nws_alerts
python src/refresh.py --source census
```

To refresh all sources using their default settings:

```bash
python src/refresh.py --source all
```

The refresh controller does not support `--dry-run`. Each individual refresh script manages its own transactions, so a failed transaction is rolled back without committing its incomplete changes. Previously committed batches or sources remain intact.

Re-running unchanged data should generally produce zero inserted or updated records, although live sources may receive additional observations between runs.

These commands use the same transaction and logging framework. Successful execution of one source does not guarantee that the others are configured or populated correctly.

The refresh pipeline is designed to support safe reruns, transactional rollback on failure, and ingestion logging. Refer to `docs/runbook.md` for source-specific procedures and troubleshooting.

### 5. Run the client SQL queries

The eight client-facing SQL queries are located in `sql/queries/`.

| Query | Client question |
|---|---|
| `q01-flood-damage-by-year.sql` | How does reported flood damage vary by state and year? |
| `q02-flood-frequency-severity.sql` | Is flood damage associated with event frequency or average severity? |
| `q03-hail-seasonality.sql` | During which months is hail exposure greatest across the target states? |
| `q04-billion-dollar-episodes.sql` | How many NOAA storm episodes exceeded $1 billion in reported property damage per decade? |
| `q05-fatalities-vs-damage.sql` | Which storm types have high fatalities relative to recorded property damage? |
| `q06-county-damage-per-capita.sql` | Which counties have the greatest reported storm damage per resident? |
| `q07-hurricane-peak-winds.sql` | Which Atlantic storms recorded the strongest winds within the Southeast coastal region? |
| `q08-hurricane-station-proximity.sql` | Which weather stations were within 50 kilometers of hurricane track points? |

The queries use SQL aggregation, joins, window functions, and latitude/longitude spatial filtering.

Results depend on the loaded data. In particular, the billion-dollar episode analysis uses nominal reported NOAA property damage, not NOAA's official inflation-adjusted billion-dollar disaster classification.

### 6. Run the SQL validation tests

Each client query has a corresponding validation test in `sql/tests/`.

The tests are named `t01` through `t08`, corresponding to queries `q01` through `q08`.

**A passing test returns zero rows.** A nonempty result indicates a condition that requires investigation.

All eight client queries were executed successfully against the Team Prancer database, and their corresponding tests returned zero rows during November 20 validation.

These tests primarily check source-data consistency and basic mathematical properties. They do not independently verify every aggregate or guarantee that all analytical results are correct.

Additional `t00` table-validation scripts are included in the repository. These are separate from the eight client-query tests and require further reconciliation with the current database schema.

### 7. Run the Python reporting command

The repository includes `src/report.py` for parameterized database reporting.

Use:

```bash
python src/report.py --help
```

to inspect its available arguments.

The reporting command should be verified against the current Prancer schema before relying on its results. Earlier versions used the course's Pennsylvania weather-station example, which is not one of the primary Southeast climate-risk analyses.

## What's in the handoff pack

| Piece | Where |
|---|---|
| **README:** Project overview and startup instructions | `README.md` |
| **Technical specification:** Architecture, geographic scope, diagrams, sources, tables, programs, queries, assumptions, and design decisions | `docs/technical-spec.md` |
| **Runbook:** Connection procedures, source refresh instructions, validation, troubleshooting, and recovery | `docs/runbook.md` |
| **Database schema:** Table definitions, constraints, and indexes | `sql/schema.sql` |
| **Refresh pipeline:** Source-specific ingestion and safe refresh operations | `src/refresh.py` |
| **Client queries:** Eight insurance risk analyses | `sql/queries/` |
| **SQL tests:** Corresponding query validation and additional database checks | `sql/tests/` |
| **Python reporting:** Parameterized database reporting | `src/report.py` |
| **Dependencies:** Python packages required by the system | `requirements.txt` |
| **AI log:** AI-assisted contributions and verification evidence | `ai/AI-LOG.md` |

The knowledge transfer takes place on **November 23, 2026**, when Team Prancer hands its Climate Risk Analytics system to Team Vixen.

The receiving team completes `docs/kt-log.md` during the knowledge-transfer session.

The final Part II technical report and visualizations are due **December 1, 2026** and are not required in the November 20 handoff package.

## Rules for this repository

### No credentials in the repository

Do not commit passwords, access tokens, API keys, or connection strings containing secrets.

The course-provided `course_db.py` uses CMU authentication to connect to the database.

### Store raw downloads locally

Raw source files belong in `data/raw/`, which is excluded from Git tracking.

The refresh process should be able to obtain necessary source data again.

### Work under the Team Prancer database role

For direct SQL sessions, use:

```sql
SET ROLE prancer_write;
SET search_path = prancer, course, public;
```

In Python:

```python
from course_db import connect

conn = connect(team="prancer")
```

### Use consistent naming conventions

Tables and columns should use lowercase `snake_case` names.

Examples include:

- `storm_events`
- `county_fips`
- `damage_property_usd`
- `begin_ts`

Clean imported column names when necessary:

```python
df.columns = df.columns.str.lower().str.replace(
    r"[^a-z0-9]+", "_", regex=True
)
```

### Follow the defined geographic scope

Insurance analyses primarily focus on Texas, Louisiana, Florida, Georgia, South Carolina, and North Carolina.

State FIPS codes are:


| State | FIPS |
|---|---|
| Texas | 48 |
| Louisiana | 22 |
| Alabama | 01 |
| Florida | 12 |
| Georgia | 13 |
| South Carolina | 45 |
| North Carolina | 37 |
| Virginia | 51 |


Hurricane tracks and other source datasets may extend beyond the target region, depending on their original geographic coverage. Client queries apply the appropriate regional filters.
