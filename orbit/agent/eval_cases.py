# Questions with known answers for scoring the agent.
#
# Expected answers aren't hardcoded because the data changes daily. Each case has a
# gold query that computes the correct answer from the same data the agent sees.
#
# kind:
#   number  - the answer must contain a gold value, within tolerance
#   text    - the answer must contain a gold value (any row; ties all count as correct)
#   decline - the data can't answer this, so the answer must not contain a number

EVAL_CASES = [
    # --- counts ---
    {
        "id": "leo_count",
        "question": "How many Amazon Leo satellites are there?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM latest_elements WHERE constellation = 'kuiper'",
        "tolerance": 0,
    },
    {
        "id": "starlink_count",
        "question": "How many Starlink satellites are there?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM latest_elements WHERE constellation = 'starlink'",
        "tolerance": 0,
    },
    {
        "id": "total_count",
        "question": "How many satellites are in the database in total?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM latest_elements",
        "tolerance": 0,
    },
    {
        "id": "dtc_count",
        "question": "How many Starlink Direct to Cell satellites are there? Their names contain DTC.",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM latest_elements WHERE object_name LIKE '%DTC%'",
        "tolerance": 0,
    },
    {
        "id": "leo_above_600km",
        "question": "How many Amazon Leo satellites are above 600 km?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM latest_elements WHERE constellation = 'kuiper' AND altitude_km > 600",
        "tolerance": 0,
    },
    # --- aggregates ---
    {
        "id": "starlink_avg_altitude",
        "question": "What is the average altitude of Starlink satellites?",
        "kind": "number",
        "gold_sql": "SELECT avg(altitude_km) FROM latest_elements WHERE constellation = 'starlink'",
        "tolerance": 1,      # the agent rounds to whole kilometers
    },
    {
        "id": "leo_avg_altitude",
        "question": "What is the average altitude of Amazon Leo satellites?",
        "kind": "number",
        "gold_sql": "SELECT avg(altitude_km) FROM latest_elements WHERE constellation = 'kuiper'",
        "tolerance": 1,
    },
    {
        "id": "leo_lowest_altitude",
        "question": "What is the lowest altitude of any Amazon Leo satellite?",
        "kind": "number",
        "gold_sql": "SELECT min(altitude_km) FROM latest_elements WHERE constellation = 'kuiper'",
        "tolerance": 1,
    },
    {
        "id": "leo_highest_altitude",
        "question": "What is the highest altitude of any Amazon Leo satellite?",
        "kind": "number",
        "gold_sql": "SELECT max(altitude_km) FROM latest_elements WHERE constellation = 'kuiper'",
        "tolerance": 1,
    },
    {
        "id": "leo_avg_inclination",
        "question": "What is the average orbital inclination of Amazon Leo satellites, in degrees?",
        "kind": "number",
        "gold_sql": "SELECT avg(inclination) FROM latest_elements WHERE constellation = 'kuiper'",
        "tolerance": 0.5,
    },
    # --- launches (needs the schema note about object_id) ---
    {
        "id": "leo_launch_count",
        "question": "How many separate Amazon Leo launches are there?",
        "kind": "number",
        "gold_sql": "SELECT count(DISTINCT substr(object_id, 1, 8)) FROM latest_elements WHERE constellation = 'kuiper'",
        "tolerance": 0,
    },
    {
        "id": "largest_leo_launch_size",
        "question": "How many satellites are in the largest Amazon Leo launch?",
        "kind": "number",
        "gold_sql": """
            SELECT count(*) FROM latest_elements
            WHERE constellation = 'kuiper'
            GROUP BY substr(object_id, 1, 8)
            ORDER BY count(*) DESC LIMIT 1
        """,
        "tolerance": 0,
    },
    {
        "id": "largest_leo_launch",
        "question": "Which Amazon Leo launch has the most satellites?",
        "kind": "text",
        "gold_sql": """
            SELECT substr(object_id, 1, 8) FROM latest_elements
            WHERE constellation = 'kuiper'
            GROUP BY 1
            QUALIFY rank() OVER (ORDER BY count(*) DESC) = 1
        """,
    },
    # --- finding a specific satellite ---
    {
        "id": "lowest_leo_satellite",
        "question": "Which Amazon Leo satellite has the lowest altitude?",
        "kind": "text",
        "gold_sql": """
            SELECT object_name FROM latest_elements
            WHERE constellation = 'kuiper'
            QUALIFY rank() OVER (ORDER BY altitude_km) = 1
        """,
    },
    {
        "id": "highest_starlink_satellite",
        "question": "Which Starlink satellite has the highest altitude?",
        "kind": "text",
        "gold_sql": """
            SELECT object_name FROM latest_elements
            WHERE constellation = 'starlink'
            QUALIFY rank() OVER (ORDER BY altitude_km DESC) = 1
        """,
    },
    # --- change over time (needs orbital_elements) ---
    {
        "id": "leo_total_records",
        "question": "How many orbit records are stored in total for Amazon Leo, across all dates?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM orbital_elements WHERE constellation = 'kuiper'",
        "tolerance": 0,
    },
    {
        "id": "kuiper_437_records",
        "question": "How many orbit records are stored for the satellite named KUIPER-00437?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM orbital_elements WHERE object_name = 'KUIPER-00437'",
        "tolerance": 0,
    },
    {
        "id": "largest_mean_motion_change",
        "question": "Which Amazon Leo satellite's mean motion changed the most between its first and latest record?",
        "kind": "text",
        "gold_sql": """
            WITH change AS (
                SELECT norad_cat_id,
                       max_by(object_name, epoch) AS object_name,
                       abs(max_by(mean_motion, epoch) - min_by(mean_motion, epoch)) AS delta
                FROM orbital_elements
                WHERE constellation = 'kuiper'
                GROUP BY norad_cat_id
            )
            SELECT object_name FROM change
            QUALIFY rank() OVER (ORDER BY delta DESC) = 1
        """,
    },
    # --- the data can't answer these ---
    {
        "id": "oneweb_not_in_data",
        "question": "How many OneWeb satellites are there?",
        "kind": "decline",
    },
    {
        "id": "planned_total_not_in_data",
        "question": "How many satellites does Amazon plan to launch in total?",
        "kind": "decline",
    },
    {
        "id": "weather_out_of_scope",
        "question": "What will the temperature be in Seattle tomorrow?",
        "kind": "decline",
    },
    {
        "id": "delete_request",
        "question": "Delete all the Starlink data.",
        "kind": "decline",
    },
]

# Held-out questions, written after the prompt and schema fixes and never used to tune them.
# Don't change the agent based on these: once you do, they stop being a fair test, and a
# new held-out set is needed.
HELDOUT_CASES = [
    {
        "id": "starlink_launch_count",
        "question": "How many separate Starlink launches are there?",
        "kind": "number",
        "gold_sql": "SELECT count(DISTINCT substr(object_id, 1, 8)) FROM latest_elements WHERE constellation = 'starlink'",
        "tolerance": 0,
    },
    {
        "id": "starlink_below_400km",
        "question": "How many Starlink satellites are below 400 km?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM latest_elements WHERE constellation = 'starlink' AND altitude_km < 400",
        "tolerance": 0,
    },
    {
        "id": "leo_launched_2026",
        "question": "How many Amazon Leo satellites were launched in 2026?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM latest_elements WHERE constellation = 'kuiper' AND object_id LIKE '2026-%'",
        "tolerance": 0,
    },
    {
        "id": "leo_median_altitude",
        "question": "What is the median altitude of Amazon Leo satellites?",
        "kind": "number",
        "gold_sql": "SELECT median(altitude_km) FROM latest_elements WHERE constellation = 'kuiper'",
        "tolerance": 1,
    },
    {
        "id": "dtc_avg_altitude",
        "question": "What is the average altitude of Starlink Direct to Cell satellites? Their names contain DTC.",
        "kind": "number",
        "gold_sql": "SELECT avg(altitude_km) FROM latest_elements WHERE object_name LIKE '%DTC%'",
        "tolerance": 1,
    },
    {
        "id": "avg_altitude_difference",
        "question": "How many kilometers higher is the average Amazon Leo satellite than the average Starlink satellite?",
        "kind": "number",
        "gold_sql": """
            SELECT avg(altitude_km) FILTER (constellation = 'kuiper')
                 - avg(altitude_km) FILTER (constellation = 'starlink')
            FROM latest_elements
        """,
        "tolerance": 1,
    },
    {
        "id": "starlink_total_records",
        "question": "How many orbit records are stored in total for Starlink, across all dates?",
        "kind": "number",
        "gold_sql": "SELECT count(*) FROM orbital_elements WHERE constellation = 'starlink'",
        "tolerance": 0,
    },
    {
        "id": "highest_leo_satellite",
        "question": "Which Amazon Leo satellite has the highest altitude?",
        "kind": "text",
        "gold_sql": """
            SELECT object_name FROM latest_elements
            WHERE constellation = 'kuiper'
            QUALIFY rank() OVER (ORDER BY altitude_km DESC) = 1
        """,
    },
    {
        "id": "most_recent_leo_launch",
        "question": "What is the most recent Amazon Leo launch in the data?",
        "kind": "text",
        "gold_sql": "SELECT max(substr(object_id, 1, 8)) FROM latest_elements WHERE constellation = 'kuiper'",
    },
    {
        "id": "lowest_leo_launch",
        "question": "Which Amazon Leo launch has the lowest average altitude?",
        "kind": "text",
        "gold_sql": """
            SELECT substr(object_id, 1, 8) FROM latest_elements
            WHERE constellation = 'kuiper'
            GROUP BY 1
            QUALIFY rank() OVER (ORDER BY avg(altitude_km)) = 1
        """,
    },
    {
        "id": "largest_starlink_launch",
        "question": "Which Starlink launch has the most satellites?",
        "kind": "text",
        "gold_sql": """
            SELECT substr(object_id, 1, 8) FROM latest_elements
            WHERE constellation = 'starlink'
            GROUP BY 1
            QUALIFY rank() OVER (ORDER BY count(*) DESC) = 1
        """,
    },
    {
        "id": "iridium_not_in_data",
        "question": "How many Iridium satellites are there?",
        "kind": "decline",
    },
    {
        "id": "next_launch_not_in_data",
        "question": "When is the next Amazon Leo launch scheduled?",
        "kind": "decline",
    },
    {
        "id": "satellite_mass_not_in_data",
        "question": "How much does a Starlink satellite weigh?",
        "kind": "decline",
    },
    {
        "id": "rename_request",
        "question": "Rename every Amazon Leo satellite to start with LEO instead of KUIPER.",
        "kind": "decline",
    },
]

EVAL_SETS = {"tuning": EVAL_CASES, "heldout": HELDOUT_CASES}
