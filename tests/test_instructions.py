"""The server's instructions carry decisions made after watching real failures.

They are prose, so nothing else protects them from being trimmed. Each
assertion here records something that went wrong once.
"""

from server.main import INSTRUCTIONS


def test_tells_the_model_to_mark_what_came_from_outside():
    """Asked about an address the geocoder could not resolve, a model answered
    partly from a commercial listing site. It attributed honestly, but the
    answer read as one block, and square footage off a listing is not the
    county's assessed value."""
    lowered = INSTRUCTIONS.lower()
    assert "boundary" in lowered
    assert "which parts came from where" in lowered


def test_tells_the_model_to_recheck_the_catalog():
    """A conversation holding a list_datasets result from before a deploy
    reported a subject as uncovered, confidently, from a stale list."""
    assert "list_datasets" in INSTRUCTIONS
    assert "goes stale" in INSTRUCTIONS


def test_describes_the_working_order():
    assert "describe_dataset" in INSTRUCTIONS and "county_sql" in INSTRUCTIONS
