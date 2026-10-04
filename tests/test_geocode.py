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


async def test_profile_address_refuses_to_profile_a_near_miss(monkeypatch):
    """A fallback match is a different building. Profiling it would report that
    building's trash day and water line as if they belonged to the address asked
    for, which is worse than returning nothing."""
    from server import main

    async def fake_geocode(**kwargs):
        return {"query": "35 W FOURTH ST", "exact_match": False, "count": 2,
                "results": [{"parcel_id": "R72 00504 0009", "address": "40 W FOURTH ST"},
                            {"parcel_id": "R72 51467 0003", "address": "28 W FOURTH ST"}]}

    monkeypatch.setattr(main.geocoder, "geocode", fake_geocode)
    out = await main.profile_address("35 W 4th St")
    assert out["found"] is False
    assert "about" not in out, "must not profile a building that was not asked about"
    assert [r["address"] for r in out["nearest_on_street"]] == ["40 W FOURTH ST", "28 W FOURTH ST"]


async def test_profile_address_says_when_an_address_covers_several_parcels(monkeypatch):
    """Downtown blocks and condos record several parcels at one address; a
    profile of the first should not read as a profile of the whole building."""
    from server import main

    async def fake_geocode(**kwargs):
        return {"query": "28 W FOURTH ST", "exact_match": True, "count": 3, "results": [
            {"parcel_id": "R72 51467 0001", "address": "28 W FOURTH ST", "latitude": 39.75, "longitude": -84.19},
            {"parcel_id": "R72 51467 0002", "address": "28 W FOURTH ST", "latitude": 39.75, "longitude": -84.19},
            {"parcel_id": "R72 51467 0003", "address": "28 W FOURTH ST", "latitude": 39.75, "longitude": -84.19},
        ]}

    monkeypatch.setattr(main.geocoder, "geocode", fake_geocode)
    monkeypatch.setattr(type(main.county), "available", property(lambda self: False))
    out = await main.profile_address("28 W Fourth St")
    assert out["found"] is True
    assert len(out["other_parcels_at_this_address"]) == 2
    assert "R72 51467 0001" in out["note_on_parcels"]
