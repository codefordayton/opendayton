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
    """The build drops undocumented columns and fails on missing ones; double-check here."""
    for table, spec in db.schema.tables.items():
        live = {c["name"] for c in db.describe(table)["columns"]}
        assert live == set(spec["columns"]), table


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
