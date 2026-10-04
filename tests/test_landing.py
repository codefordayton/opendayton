from starlette.testclient import TestClient

from server.landing import SAMPLE_QUESTIONS
from server.main import app


def test_landing_page_renders_logo_questions_and_datasets():
    client = TestClient(app)
    html = client.get("/").text
    assert "cfd-logo-stacked-dark.png" in html
    assert SAMPLE_QUESTIONS[0][1][0] in html
    assert "Lead Service Line Inventory" in html


def test_static_serves_only_known_files():
    client = TestClient(app)
    assert client.get("/static/cfd-logo-stacked-dark.png").headers["content-type"] == "image/png"
    assert client.get("/static/favicon.ico").status_code == 200
    assert client.get("/static/main.py").status_code == 404
    assert client.get("/static/..%2Fmain.py").status_code == 404


def test_start_page_renders_from_the_markdown():
    """The /start handout is generated from docs/START.md, so they cannot drift."""
    html = TestClient(app).get("/start").text
    assert "opendayton.org/mcp" in html
    assert "granite4.1:8b" in html
    assert "<pre><code>" in html, "fenced code blocks should render"
    assert "```" not in html, "raw markdown fences leaked into the page"
    assert "<h2>" in html
