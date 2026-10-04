import pytest

from server.geocode import GeocodeError, GeocoderClient, normalize_address


@pytest.mark.parametrize(
    "text, expected",
    [
        ("275 Linden Ave", "275 LINDEN AVE"),
        ("275 Linden Avenue, Dayton, OH 45403", "275 LINDEN AVE"),
        ("200 W. Norman Ave.", "200 W NORMAN AVE"),
        ("1039 bunche dr dayton ohio", "1039 BUNCHE DR"),
        ("100 South Main Street", "100 S MAIN ST"),
        ("LINDEN", "LINDEN"),
    ],
)
def test_normalize_address(text, expected):
    assert normalize_address(text) == expected


async def test_unconfigured_client_reports_unavailable():
    c = GeocoderClient(base_url="")
    assert not c.available
    with pytest.raises(GeocodeError):
        await c.geocode(address="275 Linden Ave")


@pytest.mark.parametrize(
    "typed, expected",
    [
        # Montgomery County spells numbered streets out and never uses digits,
        # but everyone types the digit form. ~6,000 parcels sit on these streets.
        ("35 W 4th St, Dayton, OH 45402", "35 W FOURTH ST"),
        ("1401 E 3rd Street", "1401 E THIRD ST"),
        ("500 S 1st St", "500 S FIRST ST"),
        ("12th Street", "TWELFTH ST"),
        # Already-spelled forms must survive untouched.
        ("35 W Fourth St", "35 W FOURTH ST"),
        # A street with a number in its name is not an ordinal.
        ("275 Linden Ave", "275 LINDEN AVE"),
    ],
)
def test_numbered_streets_translate_to_the_county_spelling(typed, expected):
    assert normalize_address(typed) == expected
