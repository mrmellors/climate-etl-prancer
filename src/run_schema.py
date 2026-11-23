from pathlib import Path
from course_db import connect  # Adjust this import to match your existing scripts

sql = Path("sql/schema.sql").read_text()

with connect(team="prancer", autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)