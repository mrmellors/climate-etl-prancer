import re
import requests
import pandas as pd
from io import BytesIO
from io import StringIO
from course_db import connect
from datetime import datetime


BASE_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"

COLUMNS = [
    "EVENT_ID",
    "EPISODE_ID",
    "STATE",
    "STATE_FIPS",
    "EVENT_TYPE",
    "CZ_TYPE",
    "CZ_FIPS",
    "CZ_NAME",
    "CZ_TIMEZONE",
    "BEGIN_DATE_TIME",
    "END_DATE_TIME",
    "DAMAGE_PROPERTY",
    "DAMAGE_CROPS",
    "DEATHS_DIRECT",
    "DEATHS_INDIRECT",
    "INJURIES_DIRECT",
    "INJURIES_INDIRECT",
    "BEGIN_LAT",
    "BEGIN_LON",
    "END_LAT",
    "END_LON",
    "MAGNITUDE",
    "MAGNITUDE_TYPE",
]


def transform_storms(df):
    # Select columns and lowercase their names
    df = df[COLUMNS].copy()
    df.columns = df.columns.str.lower()

    # Geographic identifiers (preserve leading zeros)
    for col, width in [("state_fips", 2), ("cz_fips", 3)]:
        df[col] = (
            pd.to_numeric(df[col], errors="coerce")
            .astype("Int64")
            .astype("string")
            .str.zfill(width)
        )

    # Derive county FIPS for county-reported events
    df["county_fips"] = pd.Series(pd.NA, index=df.index, dtype="string")

    mask = (
        df["cz_type"].eq("C")
        & df["state_fips"].notna()
        & df["cz_fips"].notna()
    )

    df.loc[mask, "county_fips"] = (
        df.loc[mask, "state_fips"]
        + df.loc[mask, "cz_fips"]
    )

    # Convert NOAA damage strings (e.g. 25K, 1.5M)
    def parse_damage(value):
        if pd.isna(value) or str(value).strip() == "":
            return None

        value = str(value).strip().upper()
        multipliers = {"K": 1e3, "M": 1e6, "B": 1e9}

        if value[-1] in multipliers:
            try:
                return float(value[:-1]) * multipliers[value[-1]]
            except ValueError:
                return None

        try:
            return float(value)
        except ValueError:
            return None

    df["damage_property"] = df["damage_property"].map(parse_damage)
    df["damage_crops"] = df["damage_crops"].map(parse_damage)

    # Convert dates (keep NOAA local times, not UTC)
    for col in ["begin_date_time", "end_date_time"]:
        df[col] = pd.to_datetime(
            df[col],
            format="%d-%b-%y %H:%M:%S",
            errors="coerce"
        )

        # Numeric columns
        # Integer columns
    integer_cols = [
        "event_id",
        "episode_id",
        "deaths_direct",
        "deaths_indirect",
        "injuries_direct",
        "injuries_indirect"
    ]

    for col in integer_cols:
        df[col] = pd.to_numeric(
            df[col], errors="coerce"
        ).astype("Int64")

    # Float columns
    float_cols = [
        "begin_lat",
        "begin_lon",
        "end_lat",
        "end_lon",
        "magnitude"
    ]

    for col in float_cols:
        df[col] = pd.to_numeric(
            df[col], errors="coerce"
            
        )
    # Remove impossible coordinate values
    for col in ["begin_lat", "end_lat"]:
        df.loc[~df[col].between(-90, 90), col] = pd.NA

    for col in ["begin_lon", "end_lon"]:
        df.loc[~df[col].between(-180, 180), col] = pd.NA

    return df


def load_stage(conn, df):
    """Load transformed storm events into a temporary staging table."""

    # Create a staging table with the same columns as storm_events
    conn.execute("""
        CREATE TEMP TABLE stage_storms (
            LIKE prancer.storm_events INCLUDING DEFAULTS
        ) ON COMMIT DROP
    """)

    # Convert the DataFrame to CSV text in memory
    buffer = StringIO()
    df.to_csv(buffer, index=False, na_rep="")
    buffer.seek(0)

    # Load the data into the temporary staging table
    with conn.cursor() as cur:
        with cur.copy("""
            COPY stage_storms (
                event_id,
                episode_id,
                state,
                state_fips,
                event_type,
                cz_type,
                cz_fips,
                cz_name,
                cz_timezone,
                begin_date_time,
                end_date_time,
                damage_property,
                damage_crops,
                deaths_direct,
                deaths_indirect,
                injuries_direct,
                injuries_indirect,
                begin_lat,
                begin_lon,
                end_lat,
                end_lon,
                magnitude,
                magnitude_type,
                county_fips
            )
            FROM STDIN (FORMAT csv, HEADER true)
        """) as copy:
            copy.write(buffer.getvalue().encode("utf-8"))

    print(f"Staged {len(df)} storm events.")


def validate(conn):
    checks = {
        "Missing event IDs": """
            SELECT COUNT(*)
            FROM stage_storms
            WHERE event_id IS NULL
        """,

        "Duplicate event IDs": """
            SELECT COUNT(*) - COUNT(DISTINCT event_id)
            FROM stage_storms
        """,

        "Missing start dates": """
            SELECT COUNT(*)
            FROM stage_storms
            WHERE begin_date_time IS NULL
        """
    }

    for name, query in checks.items():
        count = conn.execute(query).fetchone()[0]

        if count > 0:
            raise ValueError(f"{name}: {count} invalid records")

    print("Storm Events validation passed.")



def merge(conn):
    """Insert new storms and update existing storms if changed."""

    columns = [
        "event_id", "episode_id", "state", "state_fips",
        "event_type", "cz_type", "cz_fips", "cz_name",
        "begin_date_time", "end_date_time", "cz_timezone",
        "damage_property", "damage_crops",
        "deaths_direct", "deaths_indirect",
        "injuries_direct", "injuries_indirect",
        "begin_lat", "begin_lon", "end_lat", "end_lon",
        "magnitude", "magnitude_type", "county_fips"
    ]

    # Count new records before merging
    inserted = conn.execute("""
        SELECT COUNT(*)
        FROM stage_storms s
        WHERE NOT EXISTS (
            SELECT 1
            FROM storm_events e
            WHERE e.event_id = s.event_id
        )
    """).fetchone()[0]

    # Build SQL using a fixed, trusted list of columns
    cols = ", ".join(columns)
    updates = ", ".join(
        f"{col} = EXCLUDED.{col}"
        for col in columns
        if col != "event_id"
    )
    comparisons = ", ".join(
        f"storm_events.{col}" for col in columns
        if col != "event_id"
    )
    incoming = ", ".join(
        f"EXCLUDED.{col}" for col in columns
        if col != "event_id"
    )

    result = conn.execute(f"""
        INSERT INTO storm_events ({cols})
        SELECT {cols}
        FROM stage_storms
        ON CONFLICT (event_id)
        DO UPDATE SET {updates}
        WHERE ({comparisons}) IS DISTINCT FROM ({incoming})
    """)

    changed = result.rowcount
    updated = changed - inserted

    print(f"{inserted} inserted, {updated} updated.")

    return inserted, updated


def already_loaded(conn, filename):
    """Check whether a NOAA file was successfully ingested."""

    result = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM prancer.ingestion_runs
            WHERE source = 'storm_events'
              AND filename = %s
              AND status = 'success'
        )
        """,
        (filename,)
    ).fetchone()

    return result[0]


def record_success(conn, filename, staged, inserted, updated):
    """Record a successfully completed NOAA ingestion."""

    conn.execute(
        """
        INSERT INTO prancer.ingestion_runs (
            source,
            filename,
            status,
            rows_staged,
            rows_inserted,
            rows_updated
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            "storm_events",
            filename,
            "success",
            staged,
            inserted,
            updated
        )
    )


def refresh_storms():
    # Get NOAA's directory listing
    response = requests.get(BASE_URL, timeout=30)
    response.raise_for_status()

    html = response.text

    # Connect to PostgreSQL
    with connect(team="prancer", autocommit=True) as conn:

        # Loop over all years
        for year in range(1996, datetime.now().year + 1):

            pattern = (
                rf"StormEvents_details-ftp_v1\.0_"
                rf"d{year}_c\d{{8}}\.csv\.gz"
            )

            matches = re.findall(pattern, html)

            if not matches:
                print(f"No file found for {year}")
                continue

            # Choose the latest file version
            filename = max(matches)

            # Skip if this exact version was already loaded
            if already_loaded(conn, filename):
                print(f"Skipping {year}: already loaded")
                continue

            url = BASE_URL + filename
            print(f"Reading {year}: {filename}")

            # Download the compressed CSV into memory
            response = requests.get(url, timeout=120)
            response.raise_for_status()

            df = pd.read_csv(
                BytesIO(response.content),
                compression="gzip",
                dtype={
                    "SOURCE": "string",
                    "MAGNITUDE_TYPE": "string",
                    "FLOOD_CAUSE": "string",
                    "TOR_OTHER_WFO": "string",
                    "TOR_OTHER_CZ_STATE": "string",
                    "TOR_OTHER_CZ_NAME": "string"
                }
            )

            # Clean the NOAA data
            df = transform_storms(df)

            # Stage, validate, merge, and log in one transaction
            with conn.transaction():
                load_stage(conn, df)
                validate(conn)

                inserted, updated = merge(conn)

                record_success(
                    conn,
                    filename,
                    len(df),
                    inserted,
                    updated
                )

            print(
                f"Finished {year}: "
                f"{inserted} inserted, {updated} updated"
            )


if __name__ == "__main__":
    refresh_storms()