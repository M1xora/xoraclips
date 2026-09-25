"""
Issue #45: only the app's own origin may read API responses, and
GET /api/cookies reports whether cookies are saved without their content.
"""
import pytest
from fastapi.testclient import TestClient

import main

APP_ORIGIN = "http://localhost:5174"
OTHER_ORIGIN = "https://situs-lain.example"


def get_with_origin(origin):
    return TestClient(main.app).get("/api/health", headers={"Origin": origin})


def test_another_site_gets_no_cors_header():
    res = get_with_origin(OTHER_ORIGIN)
    assert "access-control-allow-origin" not in res.headers
    assert "access-control-allow-credentials" not in res.headers


def test_the_app_origin_is_allowed():
    res = get_with_origin(APP_ORIGIN)
    assert res.headers.get("access-control-allow-origin") == APP_ORIGIN


def test_a_preflight_from_another_site_is_refused():
    res = TestClient(main.app).options("/api/analyze", headers={
        "Origin": OTHER_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-gemini-api-key",
    })
    assert res.status_code == 400
    assert "access-control-allow-origin" not in res.headers


def test_a_preflight_from_the_app_may_send_the_key_header():
    res = TestClient(main.app).options("/api/analyze", headers={
        "Origin": APP_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-gemini-api-key",
    })
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == APP_ORIGIN


def test_default_origins_are_the_app_on_port_5174(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert main.allowed_origins() == ["http://localhost:5174", "http://127.0.0.1:5174"]


def test_allowed_origins_come_from_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://xoraclips.example , http://localhost:5174 ,")
    assert main.allowed_origins() == ["https://xoraclips.example", "http://localhost:5174"]


@pytest.fixture
def cookies_file(monkeypatch, tmp_path):
    path = tmp_path / "cookies.txt"
    monkeypatch.setattr(main, "COOKIES_PATH", path)
    return path


def test_cookie_status_never_contains_the_cookies(cookies_file):
    secret = "SECRET_SESSION_VALUE_123"
    cookies_file.write_text(
        "# Netscape HTTP Cookie File\n"
        f".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t{secret}\n"
        f".google.com\tTRUE\t/\tTRUE\t0\tHSID\t{secret}\n",
        encoding="utf-8",
    )
    res = TestClient(main.app).get("/api/cookies")
    body = res.json()
    assert "cookies_content" not in body
    assert secret not in res.text
    assert body["exists"] is True
    assert body["size"] == cookies_file.stat().st_size
    assert body["sample_lines"] == [".youtube.com", ".google.com"]


def test_cookie_status_without_cookies(cookies_file):
    body = TestClient(main.app).get("/api/cookies").json()
    assert body == {"exists": False, "has_cookies": False, "size": 0, "sample_lines": []}
