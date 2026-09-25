"""
Issue #45: only the app's own origin may read API responses or change
anything, and GET /api/cookies reports whether cookies are saved without
their content.
"""
import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import main

# The origins the middleware was built with, so a developer's backend/.env
# (ALLOWED_ORIGINS) cannot make these tests fail.
APP_ORIGIN = main.CORS_ORIGINS[0]
OTHER_ORIGIN = "https://situs-lain.example"
SECRET = "SECRET_SESSION_VALUE_123"


def client():
    return TestClient(main.app)


# ── Reading: CORS ────────────────────────────────────────────────────────

def test_the_middleware_uses_the_configured_origins():
    cors = [m for m in main.app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_origins"] is main.CORS_ORIGINS
    assert cors[0].kwargs["allow_credentials"] is False


def test_another_site_gets_no_cors_header():
    res = client().get("/api/health", headers={"Origin": OTHER_ORIGIN})
    assert "access-control-allow-origin" not in res.headers
    assert "access-control-allow-credentials" not in res.headers


def test_the_app_origin_is_allowed():
    res = client().get("/api/health", headers={"Origin": APP_ORIGIN})
    assert res.headers.get("access-control-allow-origin") == APP_ORIGIN


def preflight(origin):
    return client().options("/api/analyze", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-gemini-api-key",
    })


def test_a_preflight_from_another_site_is_refused():
    res = preflight(OTHER_ORIGIN)
    assert res.status_code == 400
    assert "access-control-allow-origin" not in res.headers


def test_a_preflight_from_the_app_may_send_the_key_header():
    res = preflight(APP_ORIGIN)
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == APP_ORIGIN


def test_default_origins_are_the_app_on_port_5174(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert main.allowed_origins() == ["http://localhost:5174", "http://127.0.0.1:5174"]


def test_allowed_origins_come_from_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://xoraclips.example/ , http://localhost:5174 ,")
    # Spaces, empty entries and a trailing "/" (a browser never sends one) are dropped.
    assert main.allowed_origins() == ["https://xoraclips.example", "http://localhost:5174"]


# ── Writing: requests that change something ─────────────────────────────

@pytest.fixture
def cookies_file(monkeypatch, tmp_path):
    path = tmp_path / "cookies.txt"
    monkeypatch.setattr(main, "COOKIES_PATH", path)
    return path


def test_another_site_cannot_replace_the_cookies(cookies_file):
    cookies_file.write_text("original", encoding="utf-8")
    # A page can send this without asking first: no Content-Type, no preflight.
    res = client().post("/api/cookies", content=b'{"cookies_content":"attacker"}',
                        headers={"Origin": OTHER_ORIGIN})
    assert res.status_code == 403
    assert cookies_file.read_text(encoding="utf-8") == "original"


def test_another_site_cannot_delete_the_cookies(cookies_file):
    cookies_file.write_text("original", encoding="utf-8")
    res = client().delete("/api/cookies", headers={"Origin": "null"})
    assert res.status_code == 403
    assert cookies_file.exists()


def test_the_app_can_save_cookies(cookies_file):
    res = client().post("/api/cookies", json={"cookies_content": "new"},
                        headers={"Origin": APP_ORIGIN})
    assert res.status_code == 200
    assert cookies_file.read_text(encoding="utf-8") == "new"


def test_a_request_without_origin_is_not_a_browser_page(cookies_file):
    res = client().post("/api/cookies", json={"cookies_content": "from curl"})
    assert res.status_code == 200


# ── Cookie status never contains the cookies ────────────────────────────

def cookie_status(cookies_file, text):
    cookies_file.write_text(text, encoding="utf-8")
    res = client().get("/api/cookies")
    assert SECRET not in res.text
    assert "cookies_content" not in res.json()
    return res.json()


def test_cookie_status_lists_domains_not_values(cookies_file):
    body = cookie_status(cookies_file,
        "# Netscape HTTP Cookie File\n"
        f".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t{SECRET}\n"
        f"#HttpOnly_.google.com\tTRUE\t/\tTRUE\t0\tHSID\t{SECRET}\n")
    assert body["exists"] is True
    assert body["size"] == cookies_file.stat().st_size
    assert body["sample_lines"] == [".youtube.com", ".google.com"]


def test_cookies_pasted_with_spaces_do_not_leak(cookies_file):
    body = cookie_status(cookies_file, f".youtube.com TRUE / TRUE 0 SID {SECRET}\n")
    assert body["sample_lines"] == [".youtube.com"]


def test_a_cookie_header_string_does_not_leak(cookies_file):
    body = cookie_status(cookies_file, f"SID={SECRET}; HSID={SECRET}\n")
    assert body["sample_lines"] == []


def test_cookie_status_without_cookies(cookies_file):
    body = client().get("/api/cookies").json()
    assert body == {"exists": False, "has_cookies": False, "size": 0, "sample_lines": []}
