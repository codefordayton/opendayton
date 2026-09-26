"""Fields deliberately withheld from the catalog.

Each entry records a judgment call made in docs/DECISIONS.md — data the
publisher makes public, but that conversational bulk access would expose in a
way the original publication format did not. If you are adding fields to a
layer and a test here fails, read the reason before changing the test.
"""

import pytest

from server.catalog import Catalog

WITHHELD = [
    # (layer, field, why)
    ("arrests", "Age", "age in years + neighborhood + charge identifies juveniles (19% of rows)"),
    ("arrests", "Arrest_Date", "exact date + demographics + neighborhood identifies individuals"),
    ("arrests", "BookingNumber", "directly identifying"),
    ("arrests", "Warrant_Number", "directly identifying"),
    ("crimes", "Commit_Date", "exact date + victim demographics identifies victims; month resolution only"),
    ("crimes", "DAY", "reconstructs the exact date from YEAR/MONTH/DAY"),
    ("crimes", "Relationship_To_Victim", "identifies domestic and sexual violence victims in small neighborhoods"),
    ("crimes", "Booking_Number", "directly identifying"),
    ("crimes", "DIBRS_Number", "case number, directly identifying"),
    ("housing_condition_2025", "PARLOC", "address list of ~4,300 vacant structures is a theft/arson target list"),
    ("housing_condition_2025", "OWNER_NAME", "owner names are not exposed anywhere"),
    ("housing_condition_2025", "OWNER_NA_1", "owner names are not exposed anywhere"),
    ("housing_condition_2025", "HINSPECTOR", "names a City inspector"),
    ("storm_drains", "nickname", "adopter-supplied free text; people put family names in it"),
    ("storm_drains", "adoptedby", "adopter name"),
    ("storm_drains", "emailaddr", "adopter contact"),
    ("storm_drains", "phoneNumber", "adopter contact"),
    ("storm_drains", "AdopteeAddress", "adopter home address"),
    ("lead_service_lines", "accountid", "water account number"),
    ("cip_active", "PROJECTMANAGER", "City staff personal contact details"),
    ("cip_active", "PMEMAIL", "City staff personal contact details"),
    ("cip_active", "PMPHONE", "City staff personal contact details"),
    ("cip_active", "CONTRACTOREMAIL", "individual contact details"),
    ("cip_active", "INSPECTORNAME", "names an individual inspector"),
]


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load()


@pytest.mark.parametrize("layer_id, field, why", WITHHELD, ids=[f"{l}.{f}" for l, f, _ in WITHHELD])
def test_field_stays_withheld(catalog, layer_id, field, why):
    layer = catalog.get(layer_id)
    assert layer.canonical_field(field) is None, f"{layer_id}.{field} must stay withheld: {why}"


# Reviewed and deliberately allowed despite matching the scan below.
ALLOWED_EXCEPTIONS = {
    # Institutional main numbers for schools, libraries and rec centers
    # (e.g. Sinclair's 937-512-3000), not anyone's personal line.
    "public_facilities.Phone": "institutional switchboard numbers",
}


def test_no_layer_exposes_an_obvious_person_field(catalog):
    """Catch-all for fields added later whose names signal a person."""
    suspicious = ("owner_name", "ownername", "firstname", "lastname", "email", "phone",
                  "booking", "warrant", "ssn", "dob", "birth")
    offenders = [
        f"{layer.id}.{name}"
        for layer in catalog
        for name in layer.field_names
        if any(s in name.lower().replace("_", "") for s in (x.replace("_", "") for x in suspicious))
        and f"{layer.id}.{name}" not in ALLOWED_EXCEPTIONS
    ]
    assert not offenders, (
        f"person-identifying fields in the catalog: {offenders}. "
        "Remove them, or add to ALLOWED_EXCEPTIONS with a reason if they are institutional."
    )
