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
