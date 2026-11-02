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
