import pytest
import duckdb

import orbit.agent.agent as agent

# --- describe_schema -------------------------------------------------------

def test_describe_schema_lists_tables_and_key_columns(sandbox):
    schema = agent.describe_schema()
    for expected in ("latest_elements", "orbital_elements", "altitude_km", "constellation"):
        assert expected in schema

# --- launch column ---------------------------------------------------------

@pytest.mark.parametrize("table", ["latest_elements", "orbital_elements"])
def test_launch_column_is_object_id_without_piece(sandbox, table):
    result = agent.run_sql(f"SELECT launch FROM {table}")
    assert result.splitlines() == ["launch", "2025-088"]

# --- run_sql: normal use ---------------------------------------------------

def test_select_returns_header_and_rows(sandbox):
    result = agent.run_sql("SELECT count(*) AS n FROM latest_elements")
    assert result.splitlines() == ["n", "1"]

def test_trailing_semicolon_is_allowed(sandbox):
    result = agent.run_sql("SELECT 1 AS x;")
    assert result.splitlines() == ["x", "1"]

def test_with_query_is_allowed(sandbox):
    result = agent.run_sql("WITH t AS (SELECT 2 AS y) SELECT y FROM t")
    assert result.splitlines() == ["y", "2"]

def test_altitude_is_plausible(sandbox):
    result = agent.run_sql("SELECT altitude_km FROM latest_elements")
    altitude = float(result.splitlines()[1])
    assert 300 < altitude < 800          # mean_motion 15.04 → low Earth orbit

def test_row_limit_is_enforced(sandbox):
    result = agent.run_sql("SELECT * FROM range(100)")
    assert len(result.splitlines()) == 1 + agent.MAX_ROWS

# --- run_sql: guardrails ---------------------------------------------------

@pytest.mark.parametrize("query", [
    "DROP TABLE orbital_elements",
    "DELETE FROM orbital_elements",
    "INSERT INTO orbital_elements SELECT * FROM orbital_elements",
    "SET enable_external_access = true",
    "",
])
def test_non_select_is_rejected(sandbox, query):
    assert agent.run_sql(query).startswith("Rejected")

def test_multiple_statements_are_rejected(sandbox):
    result = agent.run_sql("SELECT 1; DROP TABLE orbital_elements")
    assert result.startswith("Rejected")
    # and the table is still there
    assert agent.run_sql("SELECT count(*) FROM orbital_elements").splitlines()[1] == "1"

def test_sql_errors_come_back_as_text(sandbox):
    result = agent.run_sql("SELECT altitud FROM latest_elements")   # misspelled column
    assert result.startswith("SQL error")

def test_file_access_is_blocked(sandbox):
    result = agent.run_sql("SELECT * FROM read_csv('anything.csv')")
    assert result.startswith("SQL error")

def test_configuration_is_locked(sandbox):
    # defense in depth: even bypassing run_sql, file access can't be re-enabled
    with pytest.raises(duckdb.Error):
        sandbox.execute("SET enable_external_access = true")