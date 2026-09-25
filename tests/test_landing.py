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
