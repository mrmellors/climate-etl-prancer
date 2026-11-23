import pandas as pd
import requests

import io

from course_db import connect

import argparse

from datetime import date, timedelta

import time


# Configuration
BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"


TARGET_STATES = {
    "TX", "LA", "AL", "GA",
    "FL", "SC", "NC", "VA"
}

ELEMENTS = {"PRCP", "TMAX", "TMIN"}

API_URL = "https://www.ncei.noaa.gov/access/services/data/v1"


def get_stations():
  
    url = f"{BASE_URL}/ghcnd-stations.txt"

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    stations = pd.read_fwf(
        io.StringIO(response.text),
        colspecs=[
            (0, 11),
            (12, 20),
            (21, 30),
            (31, 37),
            (38, 40),
            (41, 71)
        ],
        names=[
            "station_id", "lat", "lon",
            "elevation", "state", "name"
        ],
        dtype={"station_id": "string", "state": "string"}
    )

    stations = stations[
        stations["state"].isin(TARGET_STATES)
    ].copy()

    stations["elevation"] = stations["elevation"].replace(-999.9, pd.NA)

    return stations

def get_active_station_ids(stations, year):
    url = f"{BASE_URL}/ghcnd-inventory.txt"

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    inventory = pd.read_fwf(
        io.StringIO(response.text),
        colspecs=[
            (0, 11),
            (12, 20),
            (21, 30),
            (31, 35),
            (36, 40),
            (41, 45)
        ],
        names=[
            "station_id",
            "lat",
            "lon",
            "element",
            "first_year",
            "last_year"
        ]
    )

    # Keep stations in our eight states
    inventory = inventory[
        inventory["station_id"].isin(stations["station_id"])
    ]

    # Keep our three weather variables
    inventory = inventory[
        inventory["element"].isin(ELEMENTS)
    ]

    # Keep stations reporting this year or last year
    inventory = inventory[
        inventory["last_year"] >= year - 1
    ]

    return sorted(set(inventory["station_id"]))


def read_annual_file(year, station_ids):
    url = f"{BASE_URL}/by_year/{year}.csv.gz"

    for attempt in range(5):
        try:
            response = requests.get(url, timeout=180)
            response.raise_for_status()
            break
        except (requests.exceptions.HTTPError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout):
            if attempt == 4:
                raise
            time.sleep(5)

    columns = [
        "station_id", "date", "element", "value",
        "mflag", "qflag", "sflag", "obs_time"
    ]

    df = pd.read_csv(
        io.BytesIO(response.content),
        compression="gzip",
        header=None,
        names=columns,
        low_memory=False
    )

    df = df[df["station_id"].isin(station_ids)].copy()

    df = df[df["element"].isin(ELEMENTS)].copy()

    df = df[df["qflag"].isna()].copy()

    return df


def fetch_api_data(station_ids, start_date, end_date):
    params = {
        "dataset": "daily-summaries",
        "stations": ",".join(station_ids),
        "startDate": str(start_date),
        "endDate": str(end_date),
        "dataTypes": "PRCP,TMAX,TMIN",
        "units": "metric",
        "format": "json",
    }

    for attempt in range(5):
        try:
            response = requests.get(
                API_URL,
                params=params,
                timeout=180
            )
            response.raise_for_status()
            return pd.DataFrame(response.json())

        except (
            requests.exceptions.HTTPError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout
        ):
            if attempt == 4:
                raise

            time.sleep(5)


def transform_ghcn(df):
    df = df.copy()

    # Convert dates (YYYYMMDD to datetime)
    df["date"] = pd.to_datetime(
        df["date"].astype(str),
        format="%Y%m%d",
        errors="coerce"
    )

    # Convert values to numeric
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["value"] = df["value"].replace(-9999, float("nan"))
    df["value"] = df["value"] / 10

    # Remove invalid records
    df = df.dropna(subset=["station_id", "date"])

    # Pivot to one row per station and date
    df = df.pivot(
    index=["station_id", "date"],
    columns="element",
    values="value"
    ).reset_index()

    # Rename columns to match PostgreSQL
    df = df.rename(columns={
        "TMAX": "tmax",
        "TMIN": "tmin",
        "PRCP": "precip"
    })

    # Ensure all expected columns exist
    for col in ["tmax", "tmin", "precip"]:
        if col not in df.columns:
            df[col] = pd.NA

    # Remove rows only if all three measurements are missing
    df = df.dropna(
        subset=["tmax", "tmin", "precip"],
        how="all"
    )

    # Select columns in database order
    df = df[
        ["station_id", "date", "tmax", "tmin", "precip"]
    ]

    return df


def transform_ghcn_api(df):
    if df.empty:
        return pd.DataFrame(
            columns=["station_id", "date", "tmax", "tmin", "precip"]
        )

    df = df.rename(columns={
        "STATION": "station_id",
        "DATE": "date",
        "TMAX": "tmax",
        "TMIN": "tmin",
        "PRCP": "precip"
    })

    for col in ["tmax", "tmin", "precip"]:
        if col not in df.columns:
            df[col] = pd.NA

        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    df = df.dropna(subset=["station_id", "date"])

    df = df.dropna(
        subset=["tmax", "tmin", "precip"],
        how="all"
    )

    df = df[
        ["station_id", "date", "tmax", "tmin", "precip"]
    ].copy()

    if df.duplicated(["station_id", "date"]).any():
        raise ValueError("Duplicate station-date records in API response")

    return df


def load_stations(conn, stations):
    with conn.transaction():
        with conn.cursor() as cur:

            # Get state abbreviation -> FIPS mapping
            cur.execute("""
                SELECT state_abbr, state_fips
                FROM prancer.states
            """)

            state_fips = dict(cur.fetchall())

            df = stations.copy()
            df["state_fips"] = df["state"].map(state_fips)

            if df["state_fips"].isna().any():
                raise ValueError("Some stations have no matching state FIPS")

            # Convert missing elevation values to Python None
            df["elevation"] = df["elevation"].astype(object)
            df["elevation"] = df["elevation"].where(
                df["elevation"].notna(), None
            )

            rows = [
                (
                    row.station_id,
                    row.name,
                    row.state_fips,
                    row.lat,
                    row.lon,
                    row.elevation
                )
                for row in df.itertuples(index=False)
            ]

            cur.executemany("""
                INSERT INTO prancer.stations (
                    station_id, name, state_fips,
                    lat, lon, elevation
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (station_id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    state_fips = EXCLUDED.state_fips,
                    lat = EXCLUDED.lat,
                    lon = EXCLUDED.lon,
                    elevation = EXCLUDED.elevation
            """, rows)


                        # Assign missing county FIPS using nearest county centroid
            cur.execute("""
                UPDATE prancer.stations AS s
                SET county_fips = (
                    SELECT c.county_fips
                    FROM course.counties AS c
                    WHERE LEFT(c.county_fips, 2) = s.state_fips
                      AND c.lat IS NOT NULL
                      AND c.lon IS NOT NULL
                    ORDER BY
                        ((c.lat - s.lat) * 69.0)^2
                        + (
                            (c.lon - s.lon) * 69.0
                            * COS(RADIANS(s.lat))
                        )^2
                    LIMIT 1
                )
                WHERE s.county_fips IS NULL
                  AND s.state_fips IS NOT NULL
                  AND s.lat IS NOT NULL
                  AND s.lon IS NOT NULL
            """)

            counties_updated = cur.rowcount

    print(f"Processed {len(rows):,} stations")
    print(f"Processed {counties_updated:,} missing county assignments")

# staging table
def load_stage(conn, df):
    with conn.cursor() as cur:

        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stage_ghcn (
                station_id TEXT,
                date DATE,
                tmax DOUBLE PRECISION,
                tmin DOUBLE PRECISION,
                precip DOUBLE PRECISION
            ) ON COMMIT DROP
        """)

        buffer = io.StringIO()

        df.to_csv(
            buffer,
            index=False,
            na_rep=""
        )

        buffer.seek(0)

        with cur.copy("""
            COPY stage_ghcn (
                station_id, date, tmax, tmin, precip
            )
            FROM STDIN WITH (FORMAT CSV, HEADER TRUE)
        """) as copy:
            copy.write(buffer.getvalue())


def merge_ghcn(conn):
    with conn.cursor() as cur:

        # Count new observations
        cur.execute("""
            SELECT COUNT(*)
            FROM stage_ghcn AS s
            WHERE NOT EXISTS (
                SELECT 1
                FROM prancer.observations AS o
                WHERE o.station_id = s.station_id
                  AND o.date = s.date
            )
        """)

        inserted = cur.fetchone()[0]

        # Insert new observations and update changed ones
        cur.execute("""
            INSERT INTO prancer.observations (
                station_id, date, tmax, tmin, precip
            )
            SELECT
                station_id, date, tmax, tmin, precip
            FROM stage_ghcn

            ON CONFLICT (station_id, date)
            DO UPDATE SET
                tmax = EXCLUDED.tmax,
                tmin = EXCLUDED.tmin,
                precip = EXCLUDED.precip

            WHERE (
                observations.tmax,
                observations.tmin,
                observations.precip
            ) IS DISTINCT FROM (
                EXCLUDED.tmax,
                EXCLUDED.tmin,
                EXCLUDED.precip
            )
        """)

        changed = cur.rowcount
        updated = changed - inserted


        return inserted, updated
    

def already_loaded(conn, filename):
    result = conn.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM prancer.ingestion_runs
            WHERE source = 'ghcn_daily'
              AND filename = %s
              AND status = 'success'
        )
    """, (filename,)).fetchone()

    return result[0]


def record_success(conn, filename, staged, inserted, updated):
    conn.execute("""
        INSERT INTO prancer.ingestion_runs (
            source,
            filename,
            status,
            rows_staged,
            rows_inserted,
            rows_updated
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        "ghcn_daily",
        filename,
        "success",
        staged,
        inserted,
        updated
    ))


def refresh_ghcn(start_year=1996, end_year=2025, force=False):

    stations = get_stations()
    station_ids = set(stations["station_id"])

    print(f"Selected {len(station_ids):,} stations")

    with connect(team="prancer", autocommit=True) as conn:
        load_stations(conn, stations)

    for year in range(start_year, end_year + 1):

        filename = f"{year}.csv.gz"

        # New connection for each year
        with connect(team="prancer", autocommit=True) as conn:

            if not force and already_loaded(conn, filename):
                print(f"Skipping {year}: already loaded")
                continue

            print(f"\nProcessing {year}...")

            df = read_annual_file(year, station_ids)
            df = transform_ghcn(df)

            print(f"Transformed {len(df):,} station-date rows")

            # Load and log in the same transaction
            with conn.transaction():

                load_stage(conn, df)

                inserted, updated = merge_ghcn(conn)

                record_success(
                    conn,
                    filename,
                    len(df),
                    inserted,
                    updated
                )

            print(f"{inserted:,} inserted, {updated:,} updated")
            print(f"Completed GHCN refresh for {year}")

            del df



def refresh_ghcn_api(start_date=None, end_date=None):
    today = date.today()

    if end_date is None:
        end_date = today

    if start_date is None:
        start_date = max(
        date(today.year, 1, 1),
        end_date - timedelta(days=13)
    )

    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    if start_date.year != today.year or end_date.year != today.year:
        raise ValueError("API refresh must stay within the current year")

    stations = get_stations()
    station_ids = get_active_station_ids(stations, today.year)

    print(f"Total historical stations: {len(stations):,}")
    print(f"Selected active/recent stations: {len(station_ids):,}")
    print(f"Excluded stations: {len(stations) - len(station_ids):,}")

    print(f"Fetching {start_date} through {end_date}")

    batch_size = 50
    total_inserted = 0
    total_updated = 0
    total_staged = 0

    total_batches = (len(station_ids) + batch_size - 1) // batch_size

    with connect(team="prancer", autocommit=True) as conn:
        load_stations(conn, stations)

        for i in range(0, len(station_ids), batch_size):
            batch = station_ids[i:i + batch_size]

            df = fetch_api_data(batch, start_date, end_date)
            df = transform_ghcn_api(df)

            if not df.empty:
                with conn.transaction():
                    load_stage(conn, df)
                    inserted, updated = merge_ghcn(conn)

                total_inserted += inserted
                total_updated += updated
                total_staged += len(df)

            batch_number = i // batch_size + 1

            if batch_number % 1 == 0 or batch_number == total_batches:
                print(
                    f"Batch {batch_number}/{total_batches}: "
                    f"{total_inserted:,} inserted, "
                    f"{total_updated:,} updated (cumulative)"
                )


    print(
    f"API refresh complete.\n"
    f"Rows staged: {total_staged:,}\n"
    f"Rows inserted: {total_inserted:,}\n"
    f"Rows updated: {total_updated:,}\n"
    f"Rows unchanged: "
    f"{total_staged - total_inserted - total_updated:,}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load GHCN-Daily observations"
    )

    parser.add_argument(
        "--start-year",
        type=int,
        default=1996,
        help="First year to load (inclusive)"
    )

    parser.add_argument(
        "--end-year",
        type=int,
        default=date.today().year - 1,
        help="Last year to load (inclusive)"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Reload years even if previously ingested"
    )

    parser.add_argument(
        "--mode",
        choices=["bulk", "api"],
        default="bulk"
    )

    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None
    )

    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None
    )

    args = parser.parse_args()

    if args.mode == "bulk":

        if args.start_year > args.end_year:
            parser.error(
                "start-year cannot be greater than end-year"
            )

        if args.end_year >= date.today().year:
            parser.error(
                "End year must be before the current year. "
                "Use API mode for current-year observations."
            )

        refresh_ghcn(
            args.start_year,
            args.end_year,
            force=args.force
        )

    elif args.mode == "api":

        refresh_ghcn_api(
            args.start_date,
            args.end_date
        )