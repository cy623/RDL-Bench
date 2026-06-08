from pathlib import Path
import csv
import pymysql


HOST = "relational.fel.cvut.cz"
PORT = 3306
USER = "guest"
PASSWORD = "ctu-relational"
DB = " "

OUTDIR = Path(f"mysql_csv/{DB}")
CHUNK_ROWS = 100_000 


def export_table(conn, table: str, out_path: Path) -> None:
    sql = f"SELECT * FROM `{table}`" 
    with conn.cursor() as cur, out_path.open("w", newline="", encoding="utf-8") as f:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        w = csv.writer(f)
        w.writerow(cols)
        while True:
            rows = cur.fetchmany(CHUNK_ROWS)
            if not rows:
                break
            w.writerows(rows)

def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)

    conn = pymysql.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, database=DB,
        charset="utf8mb4", autocommit=True,
        cursorclass=pymysql.cursors.SSCursor, 
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW FULL TABLES WHERE Table_type='BASE TABLE';")
            tables = [r[0] for r in cur.fetchall()]

        for t in tables:
            out_file = OUTDIR / f"{t}.csv"
            print(f"Export {t} -> {out_file}")
            export_table(conn, t, out_file)

        print("Done.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()

