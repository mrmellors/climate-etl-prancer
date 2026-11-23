import requests
import time

from course_db import connect

from datetime import datetime, timedelta, UTC

import pandas as pd
from io import StringIO

LOOKBACK_DAYS = 3

# Configuration
BASE_URL = "https://api.weather.gov/stations"

HEADERS = {
    "User-Agent": "CMU 36-614 Prancer Climate ETL (your-email@andrew.cmu.edu)",
    "Accept": "application/geo+json"
}

ASOS_URL = "https://www.ncei.noaa.gov/access/homr/file/asos-stations.txt"

TARGET_STATES = {
    "TX", "LA", "AL", "GA",
    "FL", "SC", "NC", "VA"
}

def get_asos_stations():

    response = requests.get(ASOS_URL, timeout=60)
    response.raise_for_status()

    df = pd.read_fwf(
        StringIO(response.text),
        colspecs=[
            (22, 26),
            (27, 57),
            (110, 112),
            (144, 153),
            (154, 164)
        ],
        names=[
            "station_id",
            "name",
            "state",
            "lat",
            "lon"
        ],
        skiprows=2,
        dtype={"station_id": str}
    )

    df = df[df["state"].isin(TARGET_STATES)].copy()

    df = df.dropna(subset=["station_id"])

    # Convert FAA identifiers to NWS identifiers
    # For example, MIA -> KMIA
    df["station_id"] = df["station_id"].apply(
        lambda x: "K" + x if len(x) == 3 else x
    )

    df = df.drop_duplicates(subset=["station_id"])

    print(df.groupby("state").size())
    print(f"Selected {len(df):,} ASOS stations")

    return df


def fetch_nws_data():

    rows = []

    stations = get_asos_stations()
    station_ids = stations["station_id"].tolist()

    end = datetime.now(UTC)
    start = end - timedelta(days=LOOKBACK_DAYS)

    print(f"Fetching NWS observations from {start} to {end}")

    for station in station_ids:

        url = f"{BASE_URL}/{station}/observations"

        for attempt in range(5):
            try:
                response = requests.get(
                url,
                params={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "limit": 500
                },
                headers=HEADERS,
                timeout=30)
                response.raise_for_status()
                break

            except requests.exceptions.RequestException:

                if attempt == 4:
                    raise

                print(f"Request failed for {station}. Retrying...")
                time.sleep(5)

        for feat in response.json().get("features", []):

            p = feat["properties"]

            coords = (
                (feat.get("geometry") or {})
                .get("coordinates") or []
            )

            lon, lat = coords[:2] if len(coords) >= 2 else (None, None)

            rows.append((
                station,
                p["timestamp"],
                lat,
                lon,
                p["temperature"]["value"],
                p["dewpoint"]["value"],
                p["windSpeed"]["value"],
                p["windGust"]["value"],
                p["barometricPressure"]["value"],
                p["relativeHumidity"]["value"],
                p["textDescription"]
            ))

    # Outside both loops
    df = pd.DataFrame(rows, columns=[
        "station_id",
        "observed_at",
        "lat",
        "lon",
        "temperature_c",
        "dewpoint_c",
        "wind_speed_kmh",
        "wind_gust_kmh",
        "barometric_pressure_pa",
        "relative_humidity_pct",
        "text_description"
    ])

    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)

    df["hour"] = df["observed_at"].dt.floor("h")

    df = (
        df.sort_values("observed_at")
        .drop_duplicates(subset=["station_id", "hour"], keep="last")
        .drop(columns="hour")
    )

    df["observed_at"] = df["observed_at"].dt.floor("h")

    print(f"Reduced {len(rows):,} observations to {len(df):,} hourly observations")

    # Convert missing values to None for PostgreSQL
    df = df.astype(object).where(pd.notna(df), None)

    return list(df.itertuples(index=False, name=None))


def load_stage(conn, rows):

    with conn.cursor() as cur:

        cur.execute("""
            CREATE TEMP TABLE stage_nws (
                station_id TEXT,
                observed_at TIMESTAMPTZ,
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION,
                temperature_c NUMERIC,
                dewpoint_c NUMERIC,
                wind_speed_kmh NUMERIC,
                wind_gust_kmh NUMERIC,
                barometric_pressure_pa NUMERIC,
                relative_humidity_pct NUMERIC,
                text_description TEXT
            ) ON COMMIT DROP
        """)

        with cur.copy("""
            COPY stage_nws (
                station_id,
                observed_at,
                lat,
                lon,
                temperature_c,
                dewpoint_c,
                wind_speed_kmh,
                wind_gust_kmh,
                barometric_pressure_pa,
                relative_humidity_pct,
                text_description
            )
            FROM STDIN
        """) as copy:

            for row in rows:
                copy.write_row(row)


def validate(conn):

    checks = {

        "Duplicate observations": """
            SELECT COUNT(*)
            FROM (
                SELECT station_id, observed_at
                FROM stage_nws
                GROUP BY station_id, observed_at
                HAVING COUNT(*) > 1
            ) AS duplicates
        """,

        "Missing identifiers": """
            SELECT COUNT(*)
            FROM stage_nws
            WHERE station_id IS NULL
               OR observed_at IS NULL
        """,

        "Negative wind speed": """
            SELECT COUNT(*)
            FROM stage_nws
            WHERE wind_speed_kmh < 0
               OR wind_gust_kmh < 0
        """,

        "Invalid coordinates": """
            SELECT COUNT(*)
            FROM stage_nws
            WHERE lat NOT BETWEEN -90 AND 90
               OR lon NOT BETWEEN -180 AND 180
        """,

        "Invalid humidity": """
            SELECT COUNT(*)
            FROM stage_nws
            WHERE relative_humidity_pct NOT BETWEEN 0 AND 100
        """
    }

    with conn.cursor() as cur:

        for name, query in checks.items():

            cur.execute(query)
            count = cur.fetchone()[0]

            if count:
                raise ValueError(f"{name}: {count:,} invalid rows")


def merge_nws(conn):

    with conn.cursor() as cur:

        # Count new observations
        cur.execute("""
            SELECT COUNT(*)
            FROM stage_nws AS s
            WHERE NOT EXISTS (
                SELECT 1
                FROM prancer.nws_observations AS o
                WHERE o.station_id = s.station_id
                  AND o.observed_at = s.observed_at
            )
        """)

        inserted = cur.fetchone()[0]

        # Insert new and update changed observations
        cur.execute("""
            INSERT INTO prancer.nws_observations (
                station_id,
                observed_at,
                lat,
                lon,
                temperature_c,
                dewpoint_c,
                wind_speed_kmh,
                wind_gust_kmh,
                barometric_pressure_pa,
                relative_humidity_pct,
                text_description
            )
            SELECT
                station_id,
                observed_at,
                lat,
                lon,
                temperature_c,
                dewpoint_c,
                wind_speed_kmh,
                wind_gust_kmh,
                barometric_pressure_pa,
                relative_humidity_pct,
                text_description
            FROM stage_nws

            ON CONFLICT (station_id, observed_at)
            DO UPDATE SET
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                temperature_c = EXCLUDED.temperature_c,
                dewpoint_c = EXCLUDED.dewpoint_c,
                wind_speed_kmh = EXCLUDED.wind_speed_kmh,
                wind_gust_kmh = EXCLUDED.wind_gust_kmh,
                barometric_pressure_pa = EXCLUDED.barometric_pressure_pa,
                relative_humidity_pct = EXCLUDED.relative_humidity_pct,
                text_description = EXCLUDED.text_description

            WHERE (
                nws_observations.lat,
                nws_observations.lon,
                nws_observations.temperature_c,
                nws_observations.dewpoint_c,
                nws_observations.wind_speed_kmh,
                nws_observations.wind_gust_kmh,
                nws_observations.barometric_pressure_pa,
                nws_observations.relative_humidity_pct,
                nws_observations.text_description
            ) IS DISTINCT FROM (
                EXCLUDED.lat,
                EXCLUDED.lon,
                EXCLUDED.temperature_c,
                EXCLUDED.dewpoint_c,
                EXCLUDED.wind_speed_kmh,
                EXCLUDED.wind_gust_kmh,
                EXCLUDED.barometric_pressure_pa,
                EXCLUDED.relative_humidity_pct,
                EXCLUDED.text_description
            )
        """)

        changed = cur.rowcount
        updated = changed - inserted

        return inserted, updated


def record_success(conn, staged, inserted, updated):

    conn.execute("""
        INSERT INTO prancer.ingestion_runs (
            source,
            status,
            rows_staged,
            rows_inserted,
            rows_updated
        )
        VALUES (%s, %s, %s, %s, %s)
    """, (
        "nws",
        "success",
        staged,
        inserted,
        updated
    ))


def refresh_nws():

    rows = fetch_nws_data()

    print(f"Fetched {len(rows):,} observations")

    if not rows:
        print("No NWS observations returned")
        return

    with connect(team="prancer", autocommit=True) as conn:

        with conn.transaction():

            load_stage(conn, rows)

            validate(conn)

            inserted, updated = merge_nws(conn)

            record_success(
                conn,
                len(rows),
                inserted,
                updated
            )

    print(
        f"NWS refresh complete.\n"
        f"Rows staged: {len(rows):,}\n"
        f"Rows inserted: {inserted:,}\n"
        f"Rows updated: {updated:,}\n"
        f"Rows unchanged: {len(rows) - inserted - updated:,}"
    )


if __name__ == "__main__":
    refresh_nws()