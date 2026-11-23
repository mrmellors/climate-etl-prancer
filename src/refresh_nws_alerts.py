import requests
import time

from datetime import datetime, timedelta, UTC
from course_db import connect


BASE_URL = "https://api.weather.gov/alerts"

HEADERS = {
    "User-Agent": "CMU 36-614 Prancer Climate ETL (your-email@andrew.cmu.edu)",
    "Accept": "application/geo+json"
}

TARGET_STATES = {
    "TX", "LA", "AL", "GA",
    "FL", "SC", "NC", "VA"
}

LOOKBACK_DAYS = 3


def fetch_nws_alerts():

    alerts = {}

    end = datetime.now(UTC)
    start = end - timedelta(days=LOOKBACK_DAYS)

    print(f"Fetching NWS alerts from {start} to {end}")

    for state in sorted(TARGET_STATES):

        url = BASE_URL

        params = {
            "area": state,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 500
        }

        while url:

            for attempt in range(5):
                try:
                    response = requests.get(
                        url,
                        params=params,
                        headers=HEADERS,
                        timeout=30
                    )

                    response.raise_for_status()
                    break

                except requests.exceptions.RequestException:

                    if attempt == 4:
                        raise

                    print(f"Request failed for {state}. Retrying...")
                    time.sleep(5)

            data = response.json()

            for feat in data.get("features", []):

                p = feat["properties"]

                alert_id = p["id"]

                # Extract county FIPS from SAME codes
                same_codes = (
                    (p.get("geocode") or {}).get("SAME") or []
                )

                county_fips = sorted({
                    code[1:]
                    for code in same_codes
                    if len(code) == 6
                    and code.isdigit()
                    and code[3:] != "000"
                })

                # Deduplicate alerts affecting multiple states
                alerts[alert_id] = (
                    alert_id,
                    p.get("event"),
                    p.get("severity"),
                    p.get("certainty"),
                    p.get("urgency"),
                    p.get("areaDesc"),
                    county_fips,
                    p.get("effective"),
                    p.get("expires"),
                    p.get("headline")
                )

            # Retrieve additional pages if available
            url = (data.get("pagination") or {}).get("next")
            params = None

    return list(alerts.values())


def load_stage(conn, rows):

    with conn.cursor() as cur:

        cur.execute("""
            CREATE TEMP TABLE stage_nws_alerts (
                alert_id TEXT,
                event TEXT,
                severity TEXT,
                certainty TEXT,
                urgency TEXT,
                area_desc TEXT,
                county_fips CHAR(5)[],
                effective_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ,
                headline TEXT
            ) ON COMMIT DROP
        """)

        with cur.copy("""
            COPY stage_nws_alerts (
                alert_id,
                event,
                severity,
                certainty,
                urgency,
                area_desc,
                county_fips,
                effective_at,
                expires_at,
                headline
            )
            FROM STDIN
        """) as copy:

            for row in rows:
                copy.write_row(row)



def validate(conn):

    checks = {

        "Duplicate alert IDs": """
            SELECT COUNT(*)
            FROM (
                SELECT alert_id
                FROM stage_nws_alerts
                GROUP BY alert_id
                HAVING COUNT(*) > 1
            ) AS duplicates
        """,

        "Missing required values": """
            SELECT COUNT(*)
            FROM stage_nws_alerts
            WHERE alert_id IS NULL
               OR event IS NULL
        """,

        "Invalid expiration dates": """
            SELECT COUNT(*)
            FROM stage_nws_alerts
            WHERE expires_at < effective_at
        """,

        "Invalid county FIPS format": """
            SELECT COUNT(*)
            FROM stage_nws_alerts AS a
            CROSS JOIN UNNEST(a.county_fips) AS f(code)
            WHERE code !~ '^[0-9]{5}$'
        """
    }

    with conn.cursor() as cur:

        for name, query in checks.items():

            cur.execute(query)
            count = cur.fetchone()[0]

            if count:
                raise ValueError(
                    f"{name}: {count:,} invalid rows"
                )
            

def merge_nws_alerts(conn):

    with conn.cursor() as cur:

        # Count new alerts
        cur.execute("""
            SELECT COUNT(*)
            FROM stage_nws_alerts AS s
            WHERE NOT EXISTS (
                SELECT 1
                FROM prancer.nws_alerts AS a
                WHERE a.alert_id = s.alert_id
            )
        """)

        inserted = cur.fetchone()[0]

        # Insert new alerts and update changed alerts
        cur.execute("""
            INSERT INTO prancer.nws_alerts (
                alert_id,
                event,
                severity,
                certainty,
                urgency,
                area_desc,
                county_fips,
                effective_at,
                expires_at,
                headline
            )
            SELECT
                alert_id,
                event,
                severity,
                certainty,
                urgency,
                area_desc,
                county_fips,
                effective_at,
                expires_at,
                headline
            FROM stage_nws_alerts

            ON CONFLICT (alert_id)
            DO UPDATE SET
                event = EXCLUDED.event,
                severity = EXCLUDED.severity,
                certainty = EXCLUDED.certainty,
                urgency = EXCLUDED.urgency,
                area_desc = EXCLUDED.area_desc,
                county_fips = EXCLUDED.county_fips,
                effective_at = EXCLUDED.effective_at,
                expires_at = EXCLUDED.expires_at,
                headline = EXCLUDED.headline

            WHERE (
                nws_alerts.event,
                nws_alerts.severity,
                nws_alerts.certainty,
                nws_alerts.urgency,
                nws_alerts.area_desc,
                nws_alerts.county_fips,
                nws_alerts.effective_at,
                nws_alerts.expires_at,
                nws_alerts.headline
            ) IS DISTINCT FROM (
                EXCLUDED.event,
                EXCLUDED.severity,
                EXCLUDED.certainty,
                EXCLUDED.urgency,
                EXCLUDED.area_desc,
                EXCLUDED.county_fips,
                EXCLUDED.effective_at,
                EXCLUDED.expires_at,
                EXCLUDED.headline
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
        "nws_alerts",
        "success",
        staged,
        inserted,
        updated
    ))


def refresh_nws_alerts():

    rows = fetch_nws_alerts()

    print(f"Fetched {len(rows):,} unique NWS alerts")

    with connect(team="prancer", autocommit=True) as conn:

        with conn.transaction():

            load_stage(conn, rows)

            validate(conn)

            inserted, updated = merge_nws_alerts(conn)

            record_success(
                conn,
                len(rows),
                inserted,
                updated
            )

    print(
        f"NWS alerts refresh complete.\n"
        f"Rows staged: {len(rows):,}\n"
        f"Rows inserted: {inserted:,}\n"
        f"Rows updated: {updated:,}\n"
        f"Rows unchanged: {len(rows) - inserted - updated:,}"
    )


if __name__ == "__main__":
    refresh_nws_alerts()