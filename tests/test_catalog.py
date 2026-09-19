import pytest

from server.catalog import Catalog, CatalogError, Layer


def test_catalog_loads_and_is_well_formed():
    catalog = Catalog.load()
    assert len(catalog) >= 10
    for layer in catalog:
        assert layer.url.startswith("https://")
        assert layer.fields, layer.id
        assert layer.description
        assert layer.public_via and layer.source_page, f"{layer.id} must say where the public finds it"


def test_unknown_dataset_lists_known_ids():
    with pytest.raises(CatalogError) as exc:
        Catalog.load().get("nope")
    assert "crimes" in str(exc.value)


def test_canonical_field_is_case_insensitive():
    layer = Catalog.load().get("crimes")
    assert layer.canonical_field("year") == "YEAR"
    assert layer.canonical_field("NEIGHBORHOOD") == "Neighborhood"
    assert layer.canonical_field("Booking_Number") is None


def test_duplicate_ids_rejected():
    mk = lambda i: Layer(
        id=i, title="t", theme="reference", publisher="p", public_via="v", source_page="s",
        url="https://x/FeatureServer/0", geometry="table", description="d", fields={"A": "a"},
    )
    with pytest.raises(CatalogError):
        Catalog([mk("a"), mk("a")])
