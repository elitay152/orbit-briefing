import duckdb
from ollama import chat
import logging
import time

from orbit.config import setup_logging, LAKE_GLOB, OLLAMA_MODEL

logger = logging.getLogger(__name__)

# constants
MAX_ROWS = 50
_con: duckdb.DuckDBPyConnection | None = None

COLUMN_NOTES = {
    "norad_cat_id": "unique satellite ID",
    "object_name": "e.g. 'KUIPER-00028', 'STARLINK-1007'",
    "object_id": "launch designator, e.g. '2025-088A'; first 8 characters identify the launch",
    "constellation": "'kuiper' (Amazon Leo) or 'starlink'",
    "epoch": "time the orbit record describes (UTC)",
    "mean_motion": "orbits per day; higher means a lower orbit",
    "inclination": "orbit tilt in degrees from the equator",
    "eccentricity": "orbit shape; near 0 means circular",
    "altitude_km": "approximate altitude in km (latest_elements only)",
}

TABLE_NOTES = {
    "latest_elements": "newest record per satellite; use for current-state questions",
    "orbital_elements": "every distinct record over time; use for change-over-time questions",
}

SYSTEM_PROMPT = """You answer questions about satellite constellations using a DuckDB database.

- Always get numbers from the tools; never guess or use outside knowledge for counts.
- "Amazon Leo" is constellation = 'kuiper'; "Starlink" is 'starlink'.
- If unsure of table or column names, call describe_schema first.
- If a query returns "SQL error", fix it and try again.
- Answer in one to three sentences and include the key numbers.
- Round altitudes and distances to whole kilometers.
- If the data can't answer the question, say so plainly."""

def open_sandbox() -> duckdb.DuckDBPyConnection:
    """In-memory copy of the lake; file access disabled
    before any model runs."""
    con = duckdb.connect()
    con.execute(f"""
        CREATE TABLE orbital_elements AS 
        SELECT *
        FROM read_parquet('{LAKE_GLOB}', hive_partitioning = true)
        QUALIFY ROW_NUMBER() OVER(PARTITION BY norad_cat_id, epoch
            ORDER BY source_file DESC) = 1
    """)
    con.execute("""
        CREATE VIEW latest_elements AS 
        SELECT *,
            cbrt(398600.4418 / pow(mean_motion * 2 * pi() / 86400, 2)) - 6378.137 AS altitude_km
        FROM orbital_elements
        QUALIFY ROW_NUMBER() OVER(PARTITION BY norad_cat_id
            ORDER BY epoch DESC) = 1 
    """)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con

def run_sql(query: str) -> str:
    """Run ONE read-only SQL query against the satellite database and return the rows as text.

    Tables:
      - latest_elements: the newest orbit record for each satellite, plus altitude_km.
        Use this for questions about the current state ("how many", "which are highest").
      - orbital_elements: every distinct orbit record over time (one row per satellite
        per epoch). Use this for questions about change over time.

    Rules:
      - Only SELECT or WITH ... SELECT queries; one statement; no semicolons.
      - Filter constellations with constellation = 'kuiper' (Amazon Leo) or 'starlink'.
      - At most 50 rows are returned, so aggregate (COUNT, AVG, GROUP BY) instead of
        listing many rows.
      - If unsure of column names, call describe_schema first.
      - If you get "SQL error", read the message, fix the query, and try again.

    Args:
        query: A single DuckDB SQL SELECT statement, e.g.
            "SELECT count(*) FROM latest_elements WHERE constellation = 'kuiper'".
    """
    if _con is None:
        raise RuntimeError("Sandbox not opened; call open_sandbox() first.")
    query = query.strip().removesuffix(';').strip()

    # check for single query
    if ";" in query:
        return "Rejected: only one SQL statement is allowed."

    # check read-only
    words = query.split(maxsplit=1)
    if not words or words[0].lower() not in ("select", "with"):
        return "Rejected: only SELECT queries are allowed."

    # cap rows returned
    wrapped = f"SELECT * FROM ({query}) AS q LIMIT {MAX_ROWS}"
    
    # return errors to model as text
    try:
        cursor = _con.execute(wrapped)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
    except duckdb.Error as e:
        return f"SQL error: {e}"

    lines = [" | ".join(columns)]
    lines += [" | ".join(str(v) for v in row) for row in rows]
    return "\n".join(lines)

def describe_schema() -> str:
    """Describe the satellite tables and what each column means (units, allowed values).

    Call this before writing SQL if you are unsure of table or column names.
    """
    if _con is None:
        raise RuntimeError("Sandbox not opened; call open_sandbox() first.")

    lines = []
    for table, note in TABLE_NOTES.items():
        lines.append(f"\nTable {table}: {note}")
        for name, col_type, *_ in _con.execute(f"DESCRIBE {table}").fetchall():
            meaning = COLUMN_NOTES.get(name)
            lines.append(f"  {name} {col_type}" + (f"  -- {meaning}" if meaning else ""))
    return "\n".join(lines).strip()

MAX_ROUNDS = 6
TOOLS = {"run_sql": run_sql, "describe_schema": describe_schema}

def call_tool(name: str, arguments: dict) -> str:
    """Run a tool the model asked for; unknown tools or bad arguments come back as text."""
    func = TOOLS.get(name)
    if func is None:
        return f"Unknown tool: {name}"
    
    logger.info("tool %s %s", name, arguments)
    start = time.perf_counter()
    
    try:
        return func(**arguments)
    except TypeError as e:            # model passed wrong/missing arguments
        return f"Bad arguments for {name}: {e}"
    finally:
        logger.info("tool %s took %.3fs", name, time.perf_counter() - start)

def ask(question: str) -> str:
    """Answer one question, letting the model call tools until it replies with text."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + describe_schema()},
        {"role": "user", "content": question},
    ]

    for _ in range(MAX_ROUNDS):
        start = time.perf_counter()
        response = chat(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=list(TOOLS.values()),
            options={"temperature": 0},
            keep_alive="30m"
        )
        messages.append(response.message)
        logger.info("model round took %.1fs", time.perf_counter() - start)

        if not response.message.tool_calls:
            return response.message.content          # no tool requested → final answer

        for call in response.message.tool_calls:
            result = call_tool(call.function.name, call.function.arguments)
            messages.append({"role": "tool", "content": result, "tool_name": call.function.name})

    return "Stopped: too many tool calls without an answer."

if __name__ == "__main__":
    setup_logging()
    _con = open_sandbox()          # module-level, so the tools can see it

    logger.info("Warming up %s...", OLLAMA_MODEL)
    chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": "Reply OK"}], keep_alive="30m")

    print(f"Ask about the satellites (model: {OLLAMA_MODEL}). Empty line to quit.")
    while question := input("\n> ").strip():
        print(ask(question))