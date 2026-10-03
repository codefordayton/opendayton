import pytest

from server.county import DEFAULT_DB, CountyDB, CountySQLError, CountySchema

pytestmark = pytest.mark.skipif(not DEFAULT_DB.exists(), reason="county.duckdb not built (run `uv run python -m county.build`)")


@pytest.fixture(scope="module")
def db():
    d = CountyDB()
    yield d
    d.close()


def test_schema_yaml_loads():
    s = CountySchema.load()
    assert "taxroll" in s.tables and "parcel_id" in s.tables["taxroll"]["columns"]


def test_database_matches_documentation(db):
    """The build drops undocumented columns and fails on missing ones; double-check here.

    Reads the live database directly. Going through describe() made this
    tautological, because describe() used to build its column list from the
    same YAML it was being compared against — so a documented column that
    never existed sailed through the test and was advertised to models.
    """
    for table, spec in db.schema.tables.items():
        live = {r[0] for r in db._con.execute(f"DESCRIBE {table}").fetchall()}
        assert live == set(spec["columns"]), (
            f"{table}: documented-not-built {sorted(set(spec['columns']) - live)}, "
            f"built-not-documented {sorted(live - set(spec['columns']))}"
        )


def test_describe_never_advertises_a_column_that_cannot_be_queried(db):
    """Every column county_schema reports must survive an actual SELECT."""
    for table in db.schema.tables:
        for col in db.describe(table)["columns"]:
            db.query(f'SELECT "{col["name"]}" FROM {table} LIMIT 1')


def test_no_pii_columns(db):
    rows = db.query(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE lower(column_name) SIMILAR TO '.*(owner_?name|mailingname|paddr1|paddr2|mortco|oldown).*'",
        limit=50,
    )["rows"]
    assert rows == []


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE taxroll",
        "DELETE FROM taxroll",
        "SELECT 1; SELECT 2",
        "PRAGMA database_size",
        "EXPLAIN SELECT 1",
        "COPY taxroll TO '/tmp/x.csv'",
        "ATTACH '/tmp/x.db'",
        "INSTALL httpfs",
        "SELECT * FROM read_csv('/etc/passwd')",
        "CREATE TABLE t AS SELECT 1",
        "SET threads = 8",
        "",
    ],
)
def test_rejects_non_select(db, sql):
    with pytest.raises(CountySQLError):
        db.query(sql)


def test_select_with_cte_and_join(db):
    r = db.query(
        "WITH d AS (SELECT parcel_id FROM taxroll WHERE net_delinquent > 0) "
        "SELECT count(*) AS n FROM d JOIN cama_parcel USING (parcel_id)"
    )
    assert r["rows"][0]["n"] > 0


def test_row_cap_and_truncation_flag(db):
    r = db.query("SELECT parcel_id FROM taxroll", limit=5)
    assert r["count_returned"] == 5 and r["truncated"] is True


def test_dayton_filter_is_meaningful(db):
    r = db.query("SELECT count(*) AS n FROM taxroll WHERE city_township = 'DAYTON'")
    assert 60_000 < r["rows"][0]["n"] < 90_000


def test_dates_and_money_are_typed(db):
    cols = {c["name"]: c["type"] for c in db.describe("taxroll")["columns"]}
    assert cols["foreclosure_date"] == "DATE"
    assert cols["net_delinquent"].startswith("DECIMAL")
    assert cols["sq_ft"] == "INTEGER"
    assert cols["dayton_credit"] == "VARCHAR"


def test_permit_two_digit_years_pivot_correctly(db):
    r = db.query("SELECT min(year(permit_date)) AS lo, max(year(permit_date)) AS hi FROM cama_permit")
    assert r["rows"][0]["lo"] >= 1900 and r["rows"][0]["hi"] <= 2027


def test_second_instance_in_same_process_is_still_hardened():
    """DuckDB's lock_configuration is instance-wide, so a second CountyDB cannot
    re-apply its settings. It must still come up verified, not crash or degrade."""
    a = CountyDB()
    b = CountyDB()
    try:
        for db in (a, b):
            assert db.available
            assert db._con.execute("SELECT current_setting('enable_external_access')").fetchone()[0] is False
            assert db._con.execute("SELECT current_setting('lock_configuration')").fetchone()[0] is True
            with pytest.raises(CountySQLError):
                db.query("SELECT * FROM read_csv('/etc/passwd')")
    finally:
        a.close()
        b.close()


def test_missing_table_error_names_real_tables(db):
    """DuckDB suggests internal catalog tables, which sends a model in circles."""
    with pytest.raises(CountySQLError) as exc:
        db.query("SELECT address FROM housing_condition_2025")
    msg = str(exc.value)
    assert "pg_" not in msg, f"leaked an internal catalog suggestion: {msg}"
    assert "taxroll" in msg and "cama_permit" in msg
    assert "arcgis" in msg.lower(), "should redirect City datasets to the ArcGIS tools"


def test_missing_column_error_points_at_the_schema_tool(db):
    with pytest.raises(CountySQLError) as exc:
        db.query("SELECT nope FROM taxroll")
    assert "county_schema" in str(exc.value)
