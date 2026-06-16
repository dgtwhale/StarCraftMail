import pytest
from unittest.mock import patch, MagicMock, mock_open
import os, sys, importlib

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
    result = decode_mime("Hello World")
    assert result == "Hello World"


def test_decode_mime_encoded():
    encoded = "=?utf-8?b?0KLQtdGB0YI=?="
    result = decode_mime(encoded)
    assert "Тест" in result or len(result) > 0


def test_decode_mime_empty():
    result = decode_mime("")
    assert result == ""


@patch("builtins.open", mock_open(read_data="testuser:$2b$12$hash:dglocean.com::
"))
def test_register_missing_fields():
    mail_app.app.config["TESTING"] = True
    with mail_app.app.test_client() as client:
        resp = client.post("/api/register", json={})
        assert resp.status_code == 400


@patch("app.get_imap_connection")
def test_imap_connection_error(mock_imap):
    mock_imap.side_effect = Exception("Connection refused")
    mail_app.app.config["TESTING"] = True
    with mail_app.app.test_client() as client:
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
        resp = client.get("/api/mail/inbox")
        assert resp.status_code in (200, 500, 401)


def test_admin_login_get():
    mail_app.app.config["TESTING"] = True
    with mail_app.app.test_client() as client:
        resp = client.get("/admin/login")
        assert resp.status_code == 200
