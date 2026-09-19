import pytest

from server.catalog import Catalog, Layer
from server.where import WhereError, validate_field_list, validate_order_by, validate_where


@pytest.fixture(scope="module")
def crimes() -> Layer:
    return Catalog.load().get("crimes")


@pytest.mark.parametrize(
    "clause, expected",
    [
        ("", "1=1"),
        (None, "1=1"),
        ("1=1", "1=1"),
        ("year = 2025", "YEAR = 2025"),
        ("neighborhood = 'FIVE OAKS' and year >= 2025", "Neighborhood = 'FIVE OAKS' AND YEAR >= 2025"),
        ("Commit_Date >= DATE '2025-01-01'", "Commit_Date >= DATE '2025-01-01'"),
        ("UPPER(Neighborhood) LIKE 'OLD%'", "UPPER(Neighborhood) LIKE 'OLD%'"),
        ("ORC_Part IN ('PART I VIOLENT', 'PART I PROPERTY')", "ORC_Part IN ('PART I VIOLENT', 'PART I PROPERTY')"),
        ("Weapon_Description IS NOT NULL", "Weapon_Description IS NOT NULL"),
        ("Victim_Age = 'O''Brien'", "Victim_Age = 'O''Brien'"),
    ],
)
def test_accepts_valid_clauses(crimes, clause, expected):
    assert validate_where(clause, crimes) == expected


@pytest.mark.parametrize(
    "clause",
    [
        "Booking_Number > 0",  # exists on the service, not on the allowlist
        "OBJECTID > 0",
        "YEAR = 2025; DROP TABLE x",
        "YEAR = 2025 -- comment",
        "YEAR = 2025 /* c */",
        "YEAR = 2025 AND (1=1",
        "YEAR = 2025)",
        'Neighborhood = "FIVE OAKS"',  # double quotes are not supported
        "YEAR = 2025 AND EXISTS (SELECT 1)",
        "x" * 2000,
    ],
)
def test_rejects_invalid_clauses(crimes, clause):
    with pytest.raises(WhereError):
        validate_where(clause, crimes)


def test_rejection_names_allowed_fields(crimes):
    with pytest.raises(WhereError) as exc:
        validate_where("Booking_Number = 1", crimes)
    assert "Allowed fields" in str(exc.value)
    assert "Neighborhood" in str(exc.value)


def test_field_list_canonicalizes_and_dedupes(crimes):
    assert validate_field_list(["year", "YEAR", "neighborhood"], crimes, what="out_fields") == [
        "YEAR",
        "Neighborhood",
    ]
    assert validate_field_list("year, neighborhood", crimes, what="out_fields") == ["YEAR", "Neighborhood"]
    with pytest.raises(WhereError):
        validate_field_list(["Booking_Number"], crimes, what="out_fields")


def test_order_by(crimes):
    assert validate_order_by("year desc, neighborhood", crimes) == "YEAR DESC, Neighborhood ASC"
    assert validate_order_by("count DESC", crimes, extra_allowed={"count"}) == "count DESC"
    with pytest.raises(WhereError):
        validate_order_by("count DESC", crimes)
    with pytest.raises(WhereError):
        validate_order_by("YEAR DESC NULLS LAST", crimes)


def test_keyword_named_fields_are_canonicalized_not_waved_through():
    catalog = Catalog.load()
    cfs = catalog.get("calls_for_service")  # has Year / Month, mixed case
    assert validate_where("year = 2026 and MONTH = 8", cfs) == "Year = 2026 AND Month = 8"
    neighborhoods = catalog.get("neighborhoods")  # has no Year field
    with pytest.raises(WhereError):
        validate_where("Year = 2026", neighborhoods)


def test_interval_and_extract_units_still_work(crimes):
    assert (
        validate_where("Commit_Date >= CURRENT_TIMESTAMP - INTERVAL '30' DAY", crimes)
        == "Commit_Date >= CURRENT_TIMESTAMP - INTERVAL '30' DAY"
    )
    assert validate_where("EXTRACT(YEAR FROM Commit_Date) = 2025", crimes) == "EXTRACT(YEAR FROM Commit_Date) = 2025"
    # `YEAR` on crimes is a real field, so this is a field comparison, not a unit
    assert validate_where("YEAR = 2025", crimes) == "YEAR = 2025"
