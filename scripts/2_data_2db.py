from pathlib import Path
import re
import duckdb


SQL_RESERVED = {
    "order", "group", "select", "where", "table", "from",
    "join", "limit", "offset", "by", "into", "as"
}


# normalize any string
def snake(s: str) -> str:
    s = re.sub(r"\W+", "_", s.strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return s or "x"


def qid(s: str) -> str:  # quote identifier
    return '"' + s.replace('"', '""') + '"'



def list_tables(db_path: str) -> list[str]:
    with duckdb.connect(db_path) as con:
        tables = con.execute("SHOW TABLES").fetchall()
    return [t[0] for t in tables]

# list column names
def list_columns(db_path: str, table: str) -> list[str]:
    """
    Return all column names of a given table in DuckDB.
    """
    con = duckdb.connect(db_path)
    cols = con.execute(
        "SELECT column_name "
        "FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? "
        "ORDER BY ordinal_position",
        [table],
    ).fetchall()
    con.close()
    return [c[0] for c in cols]


# print data from time column
def peek_time_column(
    db_path: str,
    table: str,
    time_col: str,
    limit: int = 5,
    order: str = "asc",  # "asc" or "desc"
) -> list:
    """
    Return first/last N values of a time column.
    """
    order = "ASC" if order.lower() == "asc" else "DESC"
    con = duckdb.connect(db_path)
    rows = con.execute(
        f"""
        SELECT {time_col}
        FROM {table}
        WHERE {time_col} IS NOT NULL
        ORDER BY {time_col} {order}
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def import_all(DB, RAW):
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))

    for p in sorted(RAW.glob("*.csv")):
        t = snake(p.stem)
        if t in SQL_RESERVED:
            t = f"{t}s"

        con.execute(f"CREATE OR REPLACE TABLE {qid(t)} AS SELECT * FROM read_csv_auto(?, HEADER=TRUE)", [str(p)])

        # 2) col_name to snake_case
        cols = con.execute(f"PRAGMA table_info({qid(t)})").fetchall()  # (cid,name,type,notnull,dflt,pk)
        used = set()
        for _, name, *_ in cols:
            new = snake(name)
            base, k = new, 1
            while new in used:
                k += 1
                new = f"{base}_{k}"
            used.add(new)
            if new != name:
                con.execute(f"ALTER TABLE {qid(t)} RENAME COLUMN {qid(name)} TO {qid(new)}")

        # 3) normalize DATE/TIMESTAMP
        cols = con.execute(f"PRAGMA table_info({qid(t)})").fetchall()
        for _, name, typ, *_ in cols:
            if "VARCHAR" in typ.upper() and any(k in name for k in ("date", "dt", "time", "timestamp", "datetime")):
                ok_ts = con.execute(
                    f"""
                    SELECT avg(
                        CAST(
                            (({qid(name)} IS NULL) OR (try_cast({qid(name)} AS TIMESTAMP) IS NOT NULL))
                            AS DOUBLE
                        )
                    )
                    FROM {qid(t)}
                    """
                ).fetchone()[0]
                if ok_ts is not None and ok_ts >= 0.9:
                    con.execute(
                        f"ALTER TABLE {qid(t)} ALTER COLUMN {qid(name)} SET DATA TYPE TIMESTAMP "
                        f"USING try_cast({qid(name)} AS TIMESTAMP)"
                    )
                    continue

                ok_d = con.execute(
                    f"""
                    SELECT avg(
                        CAST(
                            (({qid(name)} IS NULL) OR (try_cast({qid(name)} AS DATE) IS NOT NULL))
                            AS DOUBLE
                        )
                    )
                    FROM {qid(t)}
                    """
                ).fetchone()[0]
                if ok_d is not None and ok_d >= 0.9:
                    con.execute(
                        f"ALTER TABLE {qid(t)} ALTER COLUMN {qid(name)} SET DATA TYPE DATE "
                        f"USING try_cast({qid(name)} AS DATE)"
                    )

        print(f"[OK] {p.name} -> {t}")

    con.close()
    print(f"DB: {DB.resolve()}")



if __name__ == "__main__":
    db_name = ' '
    RAW = Path(f"mysql_csv/{db_name}")
    DB  = Path(f"DB/{db_name}.duckdb")

    import_all(DB, RAW)

    tables = list_tables(f"DB/{db_name}.duckdb")
    # tables = list_tables(f"DB/{db_name}.duckdb")
    # print(tables)

   
    