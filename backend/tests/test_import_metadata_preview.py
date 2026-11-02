"""Import-time metadata preview (doc + chunk) and draft preservation."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import ingestion
from app.db import Base, get_entity, put_entity
from app.security import Actor, current_session

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "docs" / "testdata-mideng"


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def scope():
        with factory() as db:
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    monkeypatch.setattr(ingestion, "db_session", scope)
    monkeypatch.setattr(ingestion.config, "data_dir", tmp_path)
    queued = []
    monkeypatch.setattr(ingestion, "enqueue", lambda task: queued.append(task))
    monkeypatch.setattr(
        ingestion,
        "_index",
        lambda db, doc, chunks, kb, version: {
            "tokens": None,
            "duration": 0.01,
            "collection": "test-collection",
            "dimension": 4,
        },
    )
    monkeypatch.setattr(ingestion, "_remove_vectors", lambda *args: None)
    ingestion._stopping.clear()
    actor = {"value": Actor("browser-owner", "manager", "csrf")}
    app = FastAPI()
    app.include_router(ingestion.router, prefix="/api")
    app.dependency_overrides[current_session] = lambda: actor["value"]
    with scope() as db:
        put_entity(db, "setting", {"id": "system", "batchLimit": 20, "fileLimit": 1, "importConcurrency": 2})
    with TestClient(app) as client:
        yield client, scope, actor, queued
    engine.dispose()


def create_kb(client, name="制度"):
    response = client.post("/api/knowledge-bases", json={"name": name, "tags": ["制度"], "description": "制度资料"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


SAMPLE = """---
date: 2024-03-15
version: V2.1
author: 张三
subject: 行政人事部
---

# 出差住宿报销制度

适用组织：集团总部
负责人：李四
生效日期：2024年03月15日
版本：V2.1

## 住宿标准

出差住宿费用标准为每晚500元。

## 审批流程

部门经理审批后提交财务。
"""


def test_chunk_preview_returns_metadata(env):
    client, *_ = env
    response = client.post(
        "/api/chunk-preview",
        data={
            "text": SAMPLE,
            "fileName": "出差报销制度_V2.1.md",
            "chunkSize": "400",
            "extractMetadata": "true",
            "extractMetadataMode": "rules",
            "enhanceKeywords": "true",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["chunkCount"] >= 1
    assert body.get("metadata")
    assert body["metadata"].get("docDate") == "2024-03-15" or body["metadata"].get("bizVersion")
    assert any((c.get("metadata") or {}).get("keywords") for c in body["chunks"])
    # metadata failure should not 422 — off mode still 200
    soft = client.post(
        "/api/chunk-preview",
        data={"text": SAMPLE, "fileName": "x.md", "extractMetadata": "false"},
    )
    assert soft.status_code == 200
    assert soft.json().get("metadata") is None


def test_metadata_preview_batch(env):
    client, *_ = env
    path = TESTDATA / "01_售后FAQ.md"
    assert path.exists(), path
    response = client.post(
        "/api/metadata-preview/batch",
        files=[
            ("files", (path.name, path.read_bytes(), "text/markdown")),
            ("files", ("制度_V2.1.md", SAMPLE.encode("utf-8"), "text/markdown")),
        ],
        data={"mode": "rules"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert "name" in item and "metadata" in item and "warnings" in item
        assert item["metadata"].get("status") in ("ok", "partial", "empty", "failed", "skipped")


def test_chunk_preview_enhance_skips_edited(env):
    client, *_ = env
    chunks = [
        {"id": "a", "title": "住宿标准", "content": "出差住宿费用标准为每晚500元", "metadata": {"edited": True, "keywords": ["保留"]}},
        {"id": "b", "title": "审批流程", "content": "部门经理审批后提交财务", "metadata": {}},
    ]
    response = client.post(
        "/api/chunk-preview/enhance",
        json={"fileName": "制度.md", "chunks": chunks, "force": True, "skipEdited": True},
    )
    assert response.status_code == 200, response.text
    out = response.json()["chunks"]
    assert out[0]["metadata"]["keywords"] == ["保留"]
    assert out[1]["metadata"].get("keywords")


def test_import_draft_metadata_not_overwritten(env):
    client, scope, *_ = env
    kb = create_kb(client, name="元数据草稿")
    draft = {
        "制度.md": {
            "docDate": "2020-01-01",
            "bizVersion": "手工版",
            "subject": "人工主体",
            "ownerPerson": "人工负责人",
            "keywords": ["手改关键词"],
            "likelyQuestions": ["手改问题？"],
        }
    }
    chunk_draft = {
        "制度.md": [
            {"index": 0, "metadata": {"keywords": ["块手改"], "subject": "块主题", "likelyQuestions": ["块问题？"], "edited": True}}
        ]
    }
    import json

    response = client.post(
        f"/api/knowledge-bases/{kb}/documents",
        files=[("files", ("制度.md", SAMPLE.encode("utf-8"), "text/markdown"))],
        data={
            "autoPublish": "false",
            "imageUnderstanding": "false",
            "chunkSize": "400",
            "extractMetadata": "true",
            "extractMetadataMode": "rules",
            "draftMetadataByFile": json.dumps(draft, ensure_ascii=False),
            "draftChunkMetaByFile": json.dumps(chunk_draft, ensure_ascii=False),
        },
    )
    assert response.status_code == 202, response.text
    task = response.json()["tasks"][0]
    ingestion.process_task(task["id"])
    with scope() as db:
        doc = get_entity(db, "doc", task["docId"]).payload
        meta = doc.get("metadata") or {}
        assert meta.get("bizVersion") == "手工版"
        assert meta.get("subject") == "人工主体"
        assert meta.get("ownerPerson") == "人工负责人"
        assert "手改关键词" in (meta.get("keywords") or [])
        assert (meta.get("extractor") or {}).get("edited") is True
        chunks = doc.get("draftChunks") or []
        assert chunks
        first_meta = chunks[0].get("metadata") or {}
        assert "块手改" in (first_meta.get("keywords") or [])
        assert first_meta.get("edited") is True
