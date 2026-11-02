"""Integration checks against real FastAPI/session/core routers, without cloud calls."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as database
from app import ingestion, rag, security
from app.config import config
from app.db import Base, LoginSession, get_entity, put_entity, Credential
from app.main import app


@pytest.fixture
def security_client(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(config, "data_dir", tmp_path)
    monkeypatch.setattr(config, "database_url", "sqlite://")
    monkeypatch.setattr(config, "admin_password", "")
    monkeypatch.setattr(config, "manager_password", "")
    # Authentication/core checks must not start or close a shared vector service.
    monkeypatch.setattr(ingestion, "recover_jobs", lambda: None)
    monkeypatch.setattr(ingestion, "shutdown_jobs", lambda: None)
    monkeypatch.setattr(rag, "recover_chat_runs", lambda: None)
    monkeypatch.setattr(rag, "close_vector_store", lambda: None)
    security._failures.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        passwords = json.loads((tmp_path / "bootstrap-passwords.json").read_text())
        yield client, passwords
    engine.dispose()


def anonymous(client):
    response = client.get("/api/session")
    assert response.status_code == 200
    data = response.json()
    return {"X-CSRF-Token": data["csrf"]}


def login(client, passwords, role="admin"):
    headers = anonymous(client)
    response = client.post("/api/auth/login", json={"role": role, "password": passwords[role]}, headers=headers)
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_no_cookie_cannot_read_or_modify_management(security_client):
    client, _ = security_client
    assert client.get("/api/connections").status_code == 401
    assert client.get("/api/state").status_code == 401
    assert client.patch("/api/settings", json={}).status_code == 401
    assert client.post("/api/models", json={}).status_code == 401


def test_anonymous_session_cookie_and_csrf_are_real(security_client):
    client, _ = security_client
    response = client.get("/api/session")
    assert response.json()["role"] == "user"
    assert len(response.json()["csrf"]) >= 24
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "no-store" in response.headers["cache-control"]
    assert client.post("/api/auth/login", json={"role": "user"}).status_code == 403
    assert client.post("/api/auth/login", json={"role": "user"}, headers={"X-CSRF-Token": "bad"}).status_code == 403


def test_incorrect_password_does_not_change_role(security_client):
    client, _ = security_client
    headers = anonymous(client)
    response = client.post("/api/auth/login", json={"role": "admin", "password": "incorrect-passphrase"}, headers=headers)
    assert response.status_code == 401
    assert client.get("/api/session").json()["role"] == "user"


def test_admin_login_rotates_cookie_and_rejects_cross_origin(security_client):
    client, passwords = security_client
    headers = anonymous(client)
    old_cookie = client.cookies.get(security.COOKIE)
    response = client.post("/api/auth/login", json={"role": "admin", "password": passwords["admin"]}, headers=headers)
    assert response.status_code == 200
    assert client.cookies.get(security.COOKIE) != old_cookie
    assert client.get("/api/connections").status_code == 200
    assert client.get("/api/state", headers={"Cookie": f"{security.COOKIE}={old_cookie}"}).status_code == 401
    csrf = response.json()["csrf"]
    assert client.patch("/api/settings", json={}, headers={"X-CSRF-Token": csrf, "Origin": "https://evil.invalid"}).status_code == 403
    assert client.patch("/api/settings", json={}, headers=headers).status_code == 403


def test_anonymous_users_cannot_write_knowledge_models_or_settings(security_client):
    client, _ = security_client
    headers = anonymous(client)
    assert client.post("/api/knowledge-bases", json={"name": "blocked"}, headers=headers).status_code == 403
    assert client.post("/api/models", json={}, headers=headers).status_code == 403
    assert client.patch("/api/settings", json={}, headers=headers).status_code == 403
    assert client.get("/api/logs").status_code == 403
    assert client.get("/api/state").json()["logs"] == []


def test_manager_can_maintain_knowledge_but_not_manage_services(security_client):
    client, passwords = security_client
    headers = login(client, passwords, "manager")
    assert client.post("/api/knowledge-bases", json={"name": "管理人员知识库"}, headers=headers).status_code == 201
    assert client.get("/api/connections").status_code == 403
    assert client.post("/api/models", json={}, headers=headers).status_code == 403
    assert client.patch("/api/settings", json={}, headers=headers).status_code == 403
    assert client.get("/api/configuration-export").status_code == 403
    with database.db_session() as db:
        put_entity(db, "log", {"id": "secret-chat", "source": "chat", "question": "private chat"})
        put_entity(db, "log", {"id": "maintenance", "source": "retrieval", "question": "retrieval test"})
    logs = client.get("/api/logs").json()["items"]
    assert [l["id"] for l in logs] == ["maintenance"]
    assert [l["id"] for l in client.get("/api/state").json()["logs"]] == ["maintenance"]


def test_anonymous_conversations_are_owner_scoped(security_client):
    client, _ = security_client
    headers = anonymous(client)
    created = client.post("/api/chat-sessions", json={"title": "owner one", "kbIds": []}, headers=headers)
    assert created.status_code == 200
    id = created.json()["id"]
    assert len(client.get("/api/chat-sessions").json()) == 1
    with TestClient(app, raise_server_exceptions=False) as other:
        other_headers = anonymous(other)
        assert other.get("/api/chat-sessions").json() == []
        assert other.get("/api/state").json()["sessions"] == []
        assert other.patch(f"/api/chat-sessions/{id}", json={"title": "stolen"}, headers=other_headers).status_code == 404
        assert other.delete(f"/api/chat-sessions/{id}", headers=other_headers).status_code == 404
    assert client.get("/api/chat-sessions").json()[0]["title"] == "owner one"


def test_credentials_never_appear_in_state_export_or_validation(security_client):
    client, passwords = security_client
    headers = login(client, passwords)
    sentinel = "private-key-only-for-test"
    updated = client.patch("/api/connections/aihubmix", json={"apiKey": sentinel}, headers=headers)
    assert updated.status_code == 200
    for response in [updated, client.get("/api/state"), client.get("/api/connections"), client.get("/api/configuration-export")]:
        assert sentinel not in response.text
        assert passwords["admin"] not in response.text
    with database.db_session() as db:
        stored = db.get(Credential, "aihubmix")
        assert stored and sentinel not in stored.encrypted
        hashes = get_entity(db, "setting", "passwords").payload
        assert hashes["admin"] != passwords["admin"]
        assert hashes["admin"].startswith("$argon2")
    invalid = client.patch("/api/connections/aihubmix", json={"apiKey": [sentinel]}, headers=headers)
    assert invalid.status_code == 422
    assert sentinel not in invalid.text
    assert "input" not in invalid.text
    invalid_password = client.post("/api/auth/password", json={"role": "admin", "oldPassword": passwords["admin"], "password": "short"}, headers=headers)
    assert invalid_password.status_code == 422
    assert passwords["admin"] not in invalid_password.text


def test_expired_cookie_is_not_a_management_session(security_client):
    client, passwords = security_client
    login(client, passwords)
    token_hash = hashlib.sha256(client.cookies.get(security.COOKIE).encode()).hexdigest()
    with database.db_session() as db:
        db.get(LoginSession, token_hash).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get("/api/connections").status_code == 401
    assert client.get("/api/session").json()["role"] == "user"
