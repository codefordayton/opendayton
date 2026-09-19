"""The curated dataset catalog: datasets/layers.yaml loaded into Layer objects.

The catalog is the boundary of what the server will touch. Tools take a
dataset `id` and never a URL, and every field the model can see, filter, or
group on must appear in the layer's `fields` allowlist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LAYERS_FILE = REPO_ROOT / "datasets" / "layers.yaml"
DICTIONARIES_DIR = REPO_ROOT / "datasets" / "dictionaries"

THEMES = {
    "reference",
    "public_safety",
    "housing",
    "infrastructure",
    "capital",
    "community",
    "environment",
    "regional",
}
GEOMETRIES = {"point", "polygon", "line", "table"}

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_LAYER_URL_RE = re.compile(r"^https://[^\s]+/(FeatureServer|MapServer)/\d+$")


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Layer:
    id: str
    title: str
    theme: str
    publisher: str
    public_via: str
    source_page: str
    url: str
    geometry: str
    description: str
    fields: dict[str, str]  # FIELD_NAME -> description (the allowlist)
    approx_records: int | None = None
    time_field: str | None = None
    base_where: str | None = None
    caveats: list[str] = field(default_factory=list)
    example_questions: list[str] = field(default_factory=list)

    @property
    def field_names(self) -> list[str]:
        return list(self.fields)

    def canonical_field(self, name: str) -> str | None:
        """Return the allowlisted spelling of `name` (case-insensitive), or None."""
        lowered = name.lower()
        for f in self.fields:
            if f.lower() == lowered:
                return f
        return None

    def dictionary(self) -> str | None:
        """Optional long-form dictionary markdown for this layer, if present."""
        path = DICTIONARIES_DIR / f"{self.id}.md"
        return path.read_text() if path.exists() else None


def _require(raw: dict, key: str, layer_id: str):
    if key not in raw or raw[key] in (None, ""):
        raise CatalogError(f"layer '{layer_id}': missing required key '{key}'")
    return raw[key]


def _parse_layer(raw: dict) -> Layer:
    layer_id = raw.get("id", "<no id>")
    if not _ID_RE.match(str(layer_id)):
        raise CatalogError(f"layer id '{layer_id}' must be snake_case, 2-41 chars")

    theme = _require(raw, "theme", layer_id)
    if theme not in THEMES:
        raise CatalogError(f"layer '{layer_id}': theme '{theme}' not in {sorted(THEMES)}")

    geometry = _require(raw, "geometry", layer_id)
    if geometry not in GEOMETRIES:
        raise CatalogError(f"layer '{layer_id}': geometry '{geometry}' not in {sorted(GEOMETRIES)}")

    url = _require(raw, "url", layer_id).rstrip("/")
    if not _LAYER_URL_RE.match(url):
        raise CatalogError(
            f"layer '{layer_id}': url must be a full layer URL ending in /FeatureServer/N or /MapServer/N"
        )

    fields_raw = _require(raw, "fields", layer_id)
    if not isinstance(fields_raw, dict) or not fields_raw:
        raise CatalogError(f"layer '{layer_id}': fields must be a non-empty mapping of NAME: description")
    fields = {str(k): str(v).strip() for k, v in fields_raw.items()}

    time_field = raw.get("time_field")
    if time_field and time_field not in fields:
        raise CatalogError(f"layer '{layer_id}': time_field '{time_field}' is not in fields")

    return Layer(
        id=layer_id,
        title=_require(raw, "title", layer_id),
        theme=theme,
        publisher=_require(raw, "publisher", layer_id),
        public_via=_require(raw, "public_via", layer_id),
        source_page=_require(raw, "source_page", layer_id),
        url=url,
        geometry=geometry,
        description=" ".join(_require(raw, "description", layer_id).split()),
        fields=fields,
        approx_records=raw.get("approx_records"),
        time_field=time_field,
        base_where=raw.get("base_where"),
        caveats=[str(c) for c in raw.get("caveats", []) or []],
        example_questions=[str(q) for q in raw.get("example_questions", []) or []],
    )


class Catalog:
    def __init__(self, layers: list[Layer]):
        ids = [l.id for l in layers]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise CatalogError(f"duplicate layer ids: {sorted(dupes)}")
        self._layers = {l.id: l for l in layers}

    @classmethod
    def load(cls, path: Path = LAYERS_FILE) -> "Catalog":
        with open(path) as f:
            doc = yaml.safe_load(f)
        raw_layers = (doc or {}).get("layers")
        if not isinstance(raw_layers, list) or not raw_layers:
            raise CatalogError(f"{path}: expected a top-level 'layers' list")
        return cls([_parse_layer(r) for r in raw_layers])

    def __len__(self) -> int:
        return len(self._layers)

    def __iter__(self):
        return iter(self._layers.values())

    def get(self, layer_id: str) -> Layer:
        try:
            return self._layers[layer_id]
        except KeyError:
            known = ", ".join(sorted(self._layers))
            raise CatalogError(f"unknown dataset '{layer_id}'. Known datasets: {known}") from None

    def by_theme(self, theme: str | None = None) -> list[Layer]:
        layers = list(self._layers.values())
        if theme:
            layers = [l for l in layers if l.theme == theme]
        return sorted(layers, key=lambda l: (l.theme, l.title))

    def themes(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for l in self._layers.values():
            counts[l.theme] = counts.get(l.theme, 0) + 1
        return dict(sorted(counts.items()))
