"""Publish eval gate + immutable versions + rollback bypass."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import applications as apps
from app import providers
from app.config import config
from app.db import Base, put_entity
from app.security import Actor, current_session


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def session():
        with factory() as db:
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    monkeypatch.setattr(apps, "db_session", session)
    monkeypatch.setattr(providers, "db_session", session)
    monkeypatch.setattr(config, "data_dir", tmp_path)
    monkeypatch.setattr(config, "secret_key", "")
    monkeypatch.setattr(config, "allow_private_providers", True)
    actor = {"value": Actor("owner-a", "admin", "csrf")}
    app = FastAPI()
    app.include_router(apps.router, prefix="/api")
    app.dependency_overrides[current_session] = lambda: actor["value"]
    with session() as db:
        put_entity(db, "setting", {"id": "system", "chatConcurrency": 10})
    with TestClient(app) as client:
        yield client, session, actor
    engine.dispose()


def node(id, kind, config=None):
    return {"id": id, "kind": kind, "label": id, "position": {"x": 0, "y": 0}, "config": config or {}}


def edge(a, b, handle=None):
    return {"id": a + "-" + b + ("-" + handle if handle else ""), "source": a, "target": b, **({"sourceHandle": handle} if handle else {})}


def simple(text="收到：{{input}}"):
    return {
        "name": "门禁应用",
        "description": "eval gate",
        "nodes": [
            node("start", "start"),
            node("text", "template", {"template": text}),
            node("out", "output", {"template": "{{previous.output}}"}),
        ],
        "edges": [edge("start", "text"), edge("text", "out")],
    }


def create(client, body=None):
    response = client.post("/api/applications", json=body or simple())
    assert response.status_code == 201, response.text
    return response.json()


def test_publish_without_body_still_works(env):
    client, *_ = env
    app = create(client)
    published = client.post(f"/api/applications/{app['id']}/publish")
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "published"
    assert body["publishedRevision"] == 1
    assert body.get("publishedVersions") in ([], None) or body.get("publishedVersions") == []


def test_eval_gate_blocks_when_expect_fails(env):
    client, *_ = env
    app = create(client, simple("固定答复"))
    bad = client.post(
        f"/api/applications/{app['id']}/publish",
        json={
            "requireEval": True,
            "minPassRate": 1.0,
            "evalCases": [{"input": "x", "expectContains": "绝对不会出现的串", "expectStatus": "success"}],
        },
    )
    assert bad.status_code == 422, bad.text
    detail = bad.json()["detail"]
    assert isinstance(detail, dict)
    assert "evalReport" in detail
    assert detail["evalReport"]["passed"] == 0
    # still draft
    got = client.get(f"/api/applications/{app['id']}").json()
    assert got["status"] == "draft"
    assert got.get("publishedRevision") in (None, 0)


def test_eval_gate_passes_and_records_report(env):
    client, *_ = env
    app = create(client, simple("收到：{{input}}"))
    ok = client.post(
        f"/api/applications/{app['id']}/publish",
        json={
            "requireEval": True,
            "minPassRate": 1.0,
            "evalCases": [{"input": "你好", "expectContains": "收到：你好", "expectStatus": "success"}],
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "published"
    assert body["evalReport"]["passed"] == 1
    assert body["evalReport"]["passRate"] == 1.0


def test_versions_immutable_and_rollback_bypasses_gate(env):
    client, *_ = env
    app = create(client, simple("版本一：{{input}}"))
    assert client.post(f"/api/applications/{app['id']}/publish").status_code == 200
    # edit draft
    patch = client.patch(
        f"/api/applications/{app['id']}",
        json={**simple("版本二：{{input}}"), "expectedRevision": 1},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["revision"] == 2
    # publish v2
    p2 = client.post(f"/api/applications/{app['id']}/publish")
    assert p2.status_code == 200, p2.text
    assert p2.json()["publishedRevision"] == 2
    versions = client.get(f"/api/applications/{app['id']}/versions").json()
    assert versions["publishedRevision"] == 2
    assert versions["current"]["revision"] == 2
    assert versions["current"].get("immutable") is True
    assert any(h["revision"] == 1 for h in versions["history"])
    # mutate history payload must not affect stored (immutability at API level: deep copy on publish)
    # rollback to v1 without eval
    rb = client.post(f"/api/applications/{app['id']}/rollback", json={"revision": 1})
    assert rb.status_code == 200, rb.text
    body = rb.json()
    assert body["publishedRevision"] == 1
    assert body["status"] == "published"
    assert body.get("lastRollback", {}).get("bypassedEvalGate") is True
    # published run uses rolled-back snapshot
    run = client.post(f"/api/applications/{app['id']}/run", json={"input": "测", "mode": "published"})
    assert run.status_code == 200, run.text
    assert "版本一" in run.json()["output"]


def test_require_eval_without_cases_422(env):
    client, *_ = env
    app = create(client)
    r = client.post(f"/api/applications/{app['id']}/publish", json={"requireEval": True, "evalCases": []})
    assert r.status_code == 422
