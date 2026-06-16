import pytest
from unittest.mock import patch, MagicMock
import os, sys

os.environ.setdefault("FLASK_SECRET_KEY", "test_secret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as mail_app
from app import decode_mime


def test_health():
    mail_app.app.config["TESTING"] = True
    with mail_app.app.test_client() as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"


def test_decode_mime_plain():
    assert decode_mime("Hello World") == "Hello World"


def test_decode_mime_encoded():
    encoded = "=?utf-8?b?0KLQtdGB0YI=?="
    result = decode_mime(encoded)
    assert len(result) > 0


def test_decode_mime_empty():
    assert decode_mime("") == ""


def test_register_missing_fields():
    mail_app.app.config["TESTING"] = True
    with mail_app.app.test_client() as client:
        resp = client.post("/api/register", json={})
        assert resp.status_code == 400


def test_user_login_missing_fields():
    mail_app.app.config["TESTING"] = True
    with mail_app.app.test_client() as client:
        resp = client.post("/api/user/login", json={})
        assert resp.status_code == 400


def test_inbox_requires_auth():
    mail_app.app.config["TESTING"] = True
    with mail_app.app.test_client() as client:
        resp = client.get("/api/mail/inbox")
        assert resp.status_code in (401, 302)


def test_send_mail_requires_auth():
    mail_app.app.config["TESTING"] = True
    with mail_app.app.test_client() as client:
        resp = client.post("/api/mail/send", json={})
        assert resp.status_code in (401, 302)
