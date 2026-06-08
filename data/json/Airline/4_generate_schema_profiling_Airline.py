import duckdb
import json

def profile_lookup_table(con, table_name, table_meta):
    """
    Lookup table： code-description， LLM foreign key。
    table（<=50）； lookup table（）。
    """
    row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    table_data = {
        "table_name": table_name,
        "description": table_meta.get("description", ""),
        "schema": {
            "columns": [],
            "primary_key": table_meta.get("primary_key", []),
            "foreign_keys": table_meta.get("foreign_keys", [])
        },
        "data_profiling": {
            "row_count": row_count,
            "column_stats": {}
        }
    }

    columns_info = con.execute(f"DESCRIBE {table_name}").fetchall()
    for col_info in columns_info:
        col_name, col_type = col_info[0], col_info[1]
        table_data["schema"]["columns"].append({
            "name": col_name,
            "type": col_type,
            "comment": table_meta.get("comments", {}).get(col_name, "")
        })

    if row_count == 0:
        return table_data

    if row_count <= 50:
        # table： code-description 
        rows = con.execute(f"SELECT * FROM {table_name} ORDER BY 1").fetchall()
        col_names = [c[0] for c in columns_info]
        table_data["data_profiling"]["full_enum"] = [
            {col_names[i]: str(row[i]) for i in range(len(col_names))}
            for row in rows
        ]
        table_data["data_profiling"]["note"] = "Small lookup table: full enumeration provided for LLM semantic understanding."
    else:
        #  lookup table（ l_airport, l_airport_id）： 10 
        rows = con.execute(f"SELECT * FROM {table_name} ORDER BY RANDOM() LIMIT 10").fetchall()
        col_names = [c[0] for c in columns_info]
        table_data["data_profiling"]["random_samples"] = [
            {col_names[i]: str(row[i]) for i in range(len(col_names))}
            for row in rows
        ]
        table_data["data_profiling"]["note"] = f"Large lookup table ({row_count} rows): 10 random samples provided."

    return table_data


def profile_ontime_table(con, table_name, table_meta):
    """
    table， QA question。
    """
    row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    table_data = {
        "table_name": table_name,
        "description": table_meta.get("description", ""),
        "schema": {
            "columns": [],
            "primary_key": table_meta.get("primary_key", []),
            "foreign_keys": table_meta.get("foreign_keys", [])
        },
        "data_profiling": {
            "row_count": row_count,
            "column_stats": {},
            "advanced_profiling": {}  # result
        }
    }

    # --- Schema field ---
    columns_info = con.execute(f"DESCRIBE {table_name}").fetchall()
    for col_info in columns_info:
        col_name, col_type = col_info[0], col_info[1]
        table_data["schema"]["columns"].append({
            "name": col_name,
            "type": col_type,
            "comment": table_meta.get("comments", {}).get(col_name, "")
        })

    if row_count == 0:
        return table_data

    adv = table_data["data_profiling"]["advanced_profiling"]

    # ==================================================================
    # 1. time ——  Predictive / Analytical question
    # ==================================================================
    time_range = con.execute(f"""
        SELECT MIN(year), MAX(year), MIN(month), MAX(month),
               MIN(flightdate), MAX(flightdate)
        FROM {table_name}
    """).fetchone()
    adv["time_coverage"] = {
        "year_range": [time_range[0], time_range[1]],
        "month_range": [time_range[2], time_range[3]],
        "flight_date_min": str(time_range[4]),
        "flight_date_max": str(time_range[5])
    }

    # statistics（， Predictive）
    monthly_volume = con.execute(f"""
        SELECT year, month, COUNT(*) AS flight_count
        FROM {table_name}
        GROUP BY year, month
        ORDER BY year, month
    """).fetchall()
    adv["monthly_flight_volume"] = [
        {"year": r[0], "month": r[1], "flight_count": r[2]} for r in monthly_volume
    ]

    # statistics（， Analytical/Predictive）
    dow_dist = con.execute(f"""
        SELECT dayofweek,
               COUNT(*) AS cnt,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
        FROM {table_name}
        GROUP BY dayofweek ORDER BY dayofweek
    """).fetchall()
    adv["day_of_week_distribution"] = [
        {"dayofweek": r[0], "flight_count": r[1], "pct": f"{r[2]}%"} for r in dow_dist
    ]

    # ==================================================================
    # 2.  ——  Analytical / Predictive field
    # ==================================================================
    delay_stats = con.execute(f"""
        SELECT
            -- 
            ROUND(AVG(depdelay), 2)                                         AS avg_dep_delay_min,
            ROUND(AVG(depdelayminutes), 2)                                  AS avg_dep_delay_nonneg_min,
            ROUND(SUM(CASE WHEN depdel15 = 1 THEN 1 ELSE 0 END) * 100.0
                  / COUNT(*), 2)                                             AS dep_del15_rate_pct,
            -- 
            ROUND(AVG(arrdelay), 2)                                         AS avg_arr_delay_min,
            ROUND(AVG(arrdelayminutes), 2)                                  AS avg_arr_delay_nonneg_min,
            ROUND(SUM(CASE WHEN arrdel15 = 1 THEN 1 ELSE 0 END) * 100.0
                  / COUNT(*), 2)                                             AS arr_del15_rate_pct,
            -- （，NULL=）
            ROUND(AVG(CASE WHEN carrierdelay > 0 THEN carrierdelay END), 2) AS avg_carrier_delay,
            ROUND(AVG(CASE WHEN weatherdelay > 0 THEN weatherdelay END), 2) AS avg_weather_delay,
            ROUND(AVG(CASE WHEN nasdelay > 0 THEN nasdelay END), 2)         AS avg_nas_delay,
            ROUND(AVG(CASE WHEN securitydelay > 0 THEN securitydelay END), 2) AS avg_security_delay,
            ROUND(AVG(CASE WHEN lateaircraftdelay > 0 THEN lateaircraftdelay END), 2) AS avg_lateaircraft_delay
        FROM {table_name}
    """).fetchone()

    adv["delay_statistics"] = {
        "departure_delay": {
            "avg_delay_minutes": delay_stats[0],
            "avg_delay_nonneg_minutes": delay_stats[1],
            "del15_rate": f"{delay_stats[2]}%"
        },
        "arrival_delay": {
            "avg_delay_minutes": delay_stats[3],
            "avg_delay_nonneg_minutes": delay_stats[4],
            "del15_rate": f"{delay_stats[5]}%"
        },
        "delay_cause_avg_minutes_when_occurred": {
            "carrier_delay": delay_stats[6],
            "weather_delay": delay_stats[7],
            "nas_delay": delay_stats[8],
            "security_delay": delay_stats[9],
            "late_aircraft_delay": delay_stats[10]
        }
    }

    # distribution（ Analytical，）
    arr_delay_grp = con.execute(f"""
        SELECT arrivaldelaygroups,
               COUNT(*) AS cnt,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
        FROM {table_name}
        WHERE arrivaldelaygroups IS NOT NULL
        GROUP BY arrivaldelaygroups
        ORDER BY arrivaldelaygroups
    """).fetchall()
    adv["arrival_delay_group_distribution"] = [
        {"group_code": r[0], "flight_count": r[1], "pct": f"{r[2]}%"} for r in arr_delay_grp
    ]

    # （ Analytical/Relational Reasoning）
    carrier_delay = con.execute(f"""
        SELECT uniquecarrier,
               COUNT(*) AS total_flights,
               ROUND(SUM(CASE WHEN arrdel15 = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS arr_del15_rate,
               ROUND(AVG(arrdelayminutes), 2) AS avg_arr_delay_min
        FROM {table_name}
        GROUP BY uniquecarrier
        ORDER BY arr_del15_rate DESC
        LIMIT 20
    """).fetchall()
    adv["carrier_delay_ranking"] = [
        {
            "carrier": r[0], "total_flights": r[1],
            "arr_del15_rate": f"{r[2]}%", "avg_arr_delay_min": r[3]
        } for r in carrier_delay
    ]

    # ==================================================================
    # 3.  &  ——  Relational Reasoning / Analytical
    # ==================================================================
    cancel_stats = con.execute(f"""
        SELECT
            ROUND(SUM(cancelled) * 100.0 / COUNT(*), 3) AS cancel_rate_pct,
            ROUND(SUM(diverted) * 100.0 / COUNT(*), 3)  AS divert_rate_pct
        FROM {table_name}
    """).fetchone()
    adv["cancellation_diversion"] = {
        "overall_cancel_rate": f"{cancel_stats[0]}%",
        "overall_divert_rate": f"{cancel_stats[1]}%"
    }

    # distribution（code →  l_cancellation lookup table）
    cancel_reason = con.execute(f"""
        SELECT cancellationcode,
               COUNT(*) AS cnt,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
        FROM {table_name}
        WHERE cancelled = 1 AND cancellationcode IS NOT NULL
        GROUP BY cancellationcode
        ORDER BY cnt DESC
    """).fetchall()
    adv["cancellation_reason_distribution"] = [
        {"code": r[0], "count": r[1], "pct": f"{r[2]}%"} for r in cancel_reason
    ]

    # ==================================================================
    # 4.  ——  Retrieval / Analytical question
    # ==================================================================
    # Top 20 （）
    top_routes = con.execute(f"""
        SELECT origin, dest, COUNT(*) AS flight_count,
               ROUND(AVG(distance), 1) AS avg_distance_miles
        FROM {table_name}
        GROUP BY origin, dest
        ORDER BY flight_count DESC
        LIMIT 20
    """).fetchall()
    adv["top_20_routes_by_volume"] = [
        {"origin": r[0], "dest": r[1], "flight_count": r[2], "avg_distance_miles": r[3]}
        for r in top_routes
    ]

    # Top 20 （）
    top_origin = con.execute(f"""
        SELECT origin, COUNT(*) AS departures
        FROM {table_name} GROUP BY origin ORDER BY departures DESC LIMIT 20
    """).fetchall()
    adv["top_20_origin_airports"] = [
        {"airport": r[0], "departures": r[1]} for r in top_origin
    ]

    # Top 20 （）
    top_dest = con.execute(f"""
        SELECT dest, COUNT(*) AS arrivals
        FROM {table_name} GROUP BY dest ORDER BY arrivals DESC LIMIT 20
    """).fetchall()
    adv["top_20_dest_airports"] = [
        {"airport": r[0], "arrivals": r[1]} for r in top_dest
    ]

    # （Retrieval/Analytical）
    carrier_volume = con.execute(f"""
        SELECT uniquecarrier, COUNT(*) AS total_flights
        FROM {table_name} GROUP BY uniquecarrier ORDER BY total_flights DESC
    """).fetchall()
    adv["carrier_flight_volume"] = [
        {"carrier": r[0], "total_flights": r[1]} for r in carrier_volume
    ]

    # ==================================================================
    # 5. numeric value ——  Analytical question
    # ==================================================================
    numeric_stats = con.execute(f"""
        SELECT
            MIN(distance), MAX(distance), ROUND(AVG(distance), 2),
            MIN(airtime), MAX(airtime), ROUND(AVG(airtime), 2),
            MIN(crselapsedtime), MAX(crselapsedtime), ROUND(AVG(crselapsedtime), 2),
            MIN(taxiout), MAX(taxiout), ROUND(AVG(taxiout), 2),
            MIN(taxiin), MAX(taxiin), ROUND(AVG(taxiin), 2)
        FROM {table_name}
        WHERE distance IS NOT NULL
    """).fetchone()
    adv["numeric_field_stats"] = {
        "distance_miles": {"min": numeric_stats[0], "max": numeric_stats[1], "avg": numeric_stats[2]},
        "airtime_minutes": {"min": numeric_stats[3], "max": numeric_stats[4], "avg": numeric_stats[5]},
        "crs_elapsed_time_minutes": {"min": numeric_stats[6], "max": numeric_stats[7], "avg": numeric_stats[8]},
        "taxi_out_minutes": {"min": numeric_stats[9], "max": numeric_stats[10], "avg": numeric_stats[11]},
        "taxi_in_minutes": {"min": numeric_stats[12], "max": numeric_stats[13], "avg": numeric_stats[14]}
    }

    # distribution（ Analytical）
    dist_grp = con.execute(f"""
        SELECT distancegroup, COUNT(*) AS cnt,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
        FROM {table_name}
        WHERE distancegroup IS NOT NULL
        GROUP BY distancegroup ORDER BY distancegroup
    """).fetchall()
    adv["distance_group_distribution"] = [
        {"group_code": r[0], "flight_count": r[1], "pct": f"{r[2]}%"} for r in dist_grp
    ]

    # timedistribution（ Analytical/Predictive）
    dep_blk = con.execute(f"""
        SELECT deptimeblk, COUNT(*) AS cnt,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
        FROM {table_name}
        WHERE deptimeblk IS NOT NULL
        GROUP BY deptimeblk ORDER BY deptimeblk
    """).fetchall()
    adv["departure_timeblock_distribution"] = [
        {"timeblock": r[0], "flight_count": r[1], "pct": f"{r[2]}%"} for r in dep_blk
    ]

    # ==================================================================
    # 6. field（null_ratio / distinct_values）
    # ==================================================================
    col_stats = table_data["data_profiling"]["column_stats"]
    for col_info in columns_info:
        col_name, col_type = col_info[0], col_info[1]
        try:
            base = con.execute(
                f"SELECT COUNT(*), COUNT({col_name}), COUNT(DISTINCT {col_name}) FROM {table_name}"
            ).fetchone()
            total, non_null, unique = base
            col_stats[col_name] = {
                "null_ratio": f"{round((total - non_null) / total * 100, 1)}%",
                "distinct_values": unique
            }
        except Exception as e:
            print(f"  [WARN] column stat failed for {col_name}: {e}")

    return table_data


# =====================================================================
# ：merge schema, metadata, and data profiling
# =====================================================================
def generate_llm_json(db_path, output_json_path, METADATA_INJECTION):
    print(f"Connecting to DuckDB: {db_path}...")
    con = duckdb.connect(db_path, read_only=True)

    # generate (QA Types)
    final_json = {
        "database_metadata": {
            "name": METADATA_INJECTION["database_name"],
            "description": METADATA_INJECTION["database_description"],
            "target_qa_generation_framework": [
                {
                    "Type": "Retrieval",
                    "Description": "Directly search for entities or records",
                    "Example": "Return the names of all users who have purchased the iPhone 13."
                },
                {
                    "Type": "Analytical",
                    "Description": "Aggregation, sorting, statistics",
                    "Example": "Which city had the highest average order value over the past 6 months?"
                },
                {
                    "Type": "Relational Reasoning",
                    "Description": "Multi-table joins, multi-hop logic, existence/exclusion relationships",
                    "Example": "Which users have placed orders but never left any product reviews on the platform?"
                },
                {
                    "Type": "Predictive",
                    "Description": "Inferring future behavior or state based on historical data",
                    "Example": "Based on historical behavior, which users are unlikely to place another order within the next 30 days?"
                }
            ]
        },
        "tables": []
    }

    tables_query = (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' AND table_type='BASE TABLE'"
    )
    tables = [r[0] for r in con.execute(tables_query).fetchall()]

    for table_name in tables:
        print(f"Processing table: {table_name} ...")
        table_meta = METADATA_INJECTION["tables"].get(table_name, {})

        #  metadata JSON table， 'ontime'
        if table_name == "on_time_on_time_performance_2016_1" or "on_time" in table_name:
            # table：
            table_data = profile_ontime_table(con, table_name, table_meta)
        else:
            # Lookup table：
            table_data = profile_lookup_table(con, table_name, table_meta)

        final_json["tables"].append(table_data)

    con.close()

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Done! JSON saved to: {output_json_path}")


# =====================================================================
# entry point
# =====================================================================
if __name__ == "__main__":
    database_name = "Airline"
    DB_PATH = f"DB/{database_name}.duckdb"
    OUTPUT_FILE = f"json/{database_name}/data_schema_profiling.json"

    with open(f"json/{database_name}/metadata_{database_name}.json", "r", encoding="utf-8") as f:
        METADATA_INJECTION = json.load(f)

    generate_llm_json(DB_PATH, OUTPUT_FILE, METADATA_INJECTION)