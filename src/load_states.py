import pandas as pd
from io import StringIO
from course_db import connect

def load_states(path="data/states.psv"):
    # Read the pipe-separated file
    df = pd.read_csv(path, sep="|", dtype=str)

    # Select and rename columns
    df = df[["STATE", "STUSAB", "STATE_NAME"]].rename(
        columns={
            "STATE": "state_fips",
            "STUSAB": "state_abbr",
            "STATE_NAME": "state_name"
        }
    )

    # Preserve leading zeros
    df["state_fips"] = df["state_fips"].str.zfill(2)

    # Convert to CSV in memory
    buffer = StringIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)

    with connect(team="prancer", autocommit=True) as conn:
        with conn.transaction():
            conn.execute("""
                CREATE TEMP TABLE stage_states (
                    LIKE prancer.states
                ) ON COMMIT DROP
            """)

            with conn.cursor() as cur:
                with cur.copy("""
                    COPY stage_states (
                        state_fips,
                        state_abbr,
                        state_name
                    )
                    FROM STDIN (FORMAT CSV, HEADER TRUE)
                """) as copy:
                    copy.write(buffer.getvalue().encode("utf-8"))

            conn.execute("""
                INSERT INTO prancer.states (
                    state_fips,
                    state_abbr,
                    state_name
                )
                SELECT
                    state_fips,
                    state_abbr,
                    state_name
                FROM stage_states
                WHERE TRUE
                ON CONFLICT (state_fips)
                DO UPDATE SET
                    state_abbr = EXCLUDED.state_abbr,
                    state_name = EXCLUDED.state_name
            """)

    print(f"Loaded {len(df)} state records.")


if __name__ == "__main__":
    load_states()