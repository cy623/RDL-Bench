import duckdb
import json

def profile_lookup_table(con, table_name, table_meta):
    """
    Lookup/table：， LLM foreign key。
     teams（）, seasons（）。
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
        # table
        rows = con.execute(f"SELECT * FROM {table_name} ORDER BY 1").fetchall()
        col_names = [c[0] for c in columns_info]
        table_data["data_profiling"]["full_enum"] = [
            {col_names[i]: str(row[i]) for i in range(len(col_names))}
            for row in rows
        ]
        table_data["data_profiling"]["note"] = "Small lookup table: full enumeration provided for LLM semantic understanding."
    else:
        # table（ teams table） 10 
        rows = con.execute(f"SELECT * FROM {table_name} ORDER BY RANDOM() LIMIT 10").fetchall()
        col_names = [c[0] for c in columns_info]
        table_data["data_profiling"]["random_samples"] = [
            {col_names[i]: str(row[i]) for i in range(len(col_names))}
            for row in rows
        ]
        table_data["data_profiling"]["note"] = f"Large lookup table ({row_count} rows): 10 random samples provided."

    return table_data


def profile_ncaa_results_table(con, table_name, table_meta):
    """
    table (*_results) ， QA question。
    、、distribution。
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

    columns_info = con.execute(f"DESCRIBE {table_name}").fetchall()
    col_names_list = [c[0] for c in columns_info]
    
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
    # 1. time ——  Predictive / Analytical
    # ==================================================================
    time_range = con.execute(f"""
        SELECT MIN(season), MAX(season), MIN(daynum), MAX(daynum)
        FROM {table_name}
    """).fetchone()
    adv["time_coverage"] = {
        "season_range": [time_range[0], time_range[1]],
        "daynum_range": [time_range[2], time_range[3]]
    }

    # ==================================================================
    # 2.  ——  Analytical / Predictive field
    # ==================================================================
    score_stats = con.execute(f"""
        SELECT 
            ROUND(AVG(wscore), 1) AS avg_winning_score,
            ROUND(AVG(lscore), 1) AS avg_losing_score,
            ROUND(AVG(wscore - lscore), 1) AS avg_point_margin,
            MAX(wscore) AS max_score_single_game,
            MAX(wscore - lscore) AS max_point_margin,
            SUM(CASE WHEN numot > 0 THEN 1 ELSE 0 END) AS total_overtime_games
        FROM {table_name}
    """).fetchone()
    
    adv["scoring_and_overtime_statistics"] = {
        "avg_winning_score": score_stats[0],
        "avg_losing_score": score_stats[1],
        "avg_point_margin": score_stats[2],
        "max_score_single_game": score_stats[3],
        "max_point_margin": score_stats[4],
        "overtime_games_count": score_stats[5],
        "overtime_rate": f"{round((score_stats[5] / row_count) * 100, 2)}%"
    }

    # ==================================================================
    # 3.  (Home/Away/Neutral) ——  Relational / Predictive
    # ==================================================================
    loc_dist = con.execute(f"""
        SELECT wloc,
               COUNT(*) AS wins,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS win_pct
        FROM {table_name}
        GROUP BY wloc ORDER BY wins DESC
    """).fetchall()
    adv["winning_location_distribution"] = [
        {"location": r[0], "wins": r[1], "percentage": f"{r[2]}%"} for r in loc_dist
    ]

    # ==================================================================
    # 4.  ——  Retrieval / Analytical
    # ==================================================================
    top_teams = con.execute(f"""
        SELECT wteam, COUNT(*) AS total_wins, 
               ROUND(AVG(wscore), 1) AS avg_pts_when_winning
        FROM {table_name}
        GROUP BY wteam
        ORDER BY total_wins DESC
        LIMIT 10
    """).fetchall()
    adv["top_10_teams_by_wins"] = [
        {"team_id": r[0], "total_wins": r[1], "avg_pts_when_winning": r[2]} for r in top_teams
    ]

    # ==================================================================
    # 5.  ( detailed table)
    # ==================================================================
    if "wfgm" in col_names_list:  # check detailed tablecolumn
        detailed_stats = con.execute(f"""
            SELECT 
                ROUND(AVG(wfgm3), 1) AS avg_winner_3pt_made,
                ROUND(AVG(lfgm3), 1) AS avg_loser_3pt_made,
                ROUND(AVG(wto), 1) AS avg_winner_turnovers,
                ROUND(AVG(lto), 1) AS avg_loser_turnovers,
                ROUND(AVG(wast), 1) AS avg_winner_assists,
                ROUND(AVG(last), 1) AS avg_loser_assists
            FROM {table_name}
        """).fetchone()
        adv["advanced_box_score_averages"] = {
            "3_pointers_made": {"winner": detailed_stats[0], "loser": detailed_stats[1]},
            "turnovers": {"winner": detailed_stats[2], "loser": detailed_stats[3]},
            "assists": {"winner": detailed_stats[4], "loser": detailed_stats[5]}
        }

    # ==================================================================
    # 6. field（null_ratio / distinct_values）
    # ==================================================================
    col_stats = table_data["data_profiling"]["column_stats"]
    for col_info in columns_info:
        col_name = col_info[0]
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

        #  NCAA table Profile 
        if "results" in table_name:
            # table：
            table_data = profile_ncaa_results_table(con, table_name, table_meta)
        else:
            # table (target, teams, seasons, tourney_seeds ) 
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
    database_name = "NCAA"  # database
    DB_PATH = f"DB/{database_name}.duckdb"
    OUTPUT_FILE = f"json/{database_name}/data_schema_profiling.json"

    with open(f"json/{database_name}/metadata_{database_name}.json", "r", encoding="utf-8") as f:
        METADATA_INJECTION = json.load(f)

    generate_llm_json(DB_PATH, OUTPUT_FILE, METADATA_INJECTION)