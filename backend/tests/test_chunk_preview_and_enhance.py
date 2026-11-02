"""Chunk preview API + per-chunk keyword enhance (rules, no forged tokens)."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import ingestion, parsers
from app.db import Base, get_entity, put_entity
from app.metadata_extract import enhance_chunks_with_keywords
from app.parsers import parse_file
from app.security import Actor, current_session

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_MIDENG = ROOT / "qa" / "fixtures" / "mideng"
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
    queued, indexed, removed = [], [], []
    monkeypatch.setattr(ingestion, "enqueue", lambda task: queued.append(task))

    def index(db, doc, chunks, kb, version):
        indexed.append((doc["id"], chunks, kb, version))
        return {"tokens": None, "duration": 0.01, "collection": "test-collection", "dimension": 4}

    monkeypatch.setattr(ingestion, "_index", index)
    monkeypatch.setattr(ingestion, "_remove_vectors", lambda *args: removed.append(args))
    ingestion._stopping.clear()
    actor = {"value": Actor("browser-owner", "manager", "csrf")}
    app = FastAPI()
    app.include_router(ingestion.router, prefix="/api")
    app.dependency_overrides[current_session] = lambda: actor["value"]
    with scope() as db:
        put_entity(db, "setting", {"id": "system", "batchLimit": 20, "fileLimit": 1, "importConcurrency": 2})
    with TestClient(app) as client:
        yield client, scope, actor, queued, indexed, removed
    engine.dispose()


def create_kb(client, name="制度"):
    response = client.post("/api/knowledge-bases", json={"name": name, "tags": ["制度"], "description": "制度资料"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_enhance_chunks_with_keywords_rules():
    chunks = [
        {"id": "1", "title": "住宿标准", "content": "出差住宿费用标准为每晚500元，超标需审批。"},
        {"id": "2", "title": "已有关键词", "content": "正文", "metadata": {"keywords": ["保留"]}},
    ]
    warnings = enhance_chunks_with_keywords(chunks, "差旅报销制度.md")
    assert warnings == []
    assert chunks[0]["metadata"]["keywords"]
    joined = "".join(chunks[0]["metadata"]["keywords"])
    assert any(x in joined for x in ("住宿", "出差", "报销", "费用", "审批", "标准"))
    assert chunks[1]["metadata"]["keywords"] == ["保留"]


def test_enhance_failure_does_not_block(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.metadata_extract._keyword_candidates", boom)
    chunks = [{"id": "1", "title": "t", "content": "正文内容足够长"}]
    warnings = enhance_chunks_with_keywords(chunks, "x.md")
    assert warnings and "跳过" in warnings[0]


def test_parse_file_attaches_chunk_keywords(tmp_path, env):
    _, scope, *_ = env
    src = TESTDATA / "01_售后FAQ.md"
    assert src.exists(), src
    dest = tmp_path / "01_售后FAQ.md"
    dest.write_bytes(src.read_bytes())
    with scope() as db:
        result = parse_file(dest, "01_售后FAQ.md", "doc", {"imageUnderstanding": False}, db)
    assert result.chunks
    tagged = [c for c in result.chunks if (c.get("metadata") or {}).get("keywords")]
    assert tagged, "expected rule keywords on chunks"
    blob = " ".join(" ".join(c["metadata"]["keywords"]) for c in tagged)
    assert any(w in blob for w in ("售后", "退货", "发票", "FAQ", "质保", "签收", "运费", "客服", "换货", "维修"))


def test_parse_file_enhance_exception_adds_warning(tmp_path, env, monkeypatch):
    _, scope, *_ = env
    dest = tmp_path / "t.md"
    dest.write_text("# 标题\n\n一段足够长的正文用于切块测试。\n", encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("fail-all")

    monkeypatch.setattr("app.metadata_extract.enhance_chunks_with_keywords", boom)
    with scope() as db:
        result = parse_file(dest, "t.md", "doc", {"imageUnderstanding": False}, db)
    assert result.chunks
    assert any("分块关键词增强失败" in w for w in result.warnings)


def test_chunk_preview_api_with_testdata_and_fixture(env):
    client, *_ = env
    path = TESTDATA / "02_退换货与售后制度.md"
    assert path.exists(), path
    response = client.post(
        "/api/chunk-preview",
        files=[("files", (path.name, path.read_bytes(), "text/markdown"))],
        data={"chunkSize": "400", "chunkStrategy": "recursive", "enhanceKeywords": "true"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["chunkCount"] > 0
    assert body["options"]["chunkStrategy"] == "recursive"
    assert any((c.get("metadata") or {}).get("keywords") for c in body["chunks"])

    mideng = FIXTURE_MIDENG / "C1_充值与退款规则.md"
    assert mideng.exists(), mideng
    response2 = client.post(
        "/api/chunk-preview",
        files=[("files", (mideng.name, mideng.read_bytes(), "text/markdown"))],
        data={"chunkSize": "500", "chunkStrategy": "parent_child", "parentSize": "1200", "chunkOverlap": "40"},
    )
    assert response2.status_code == 200, response2.text
    body2 = response2.json()
    assert body2["chunkCount"] > 0
    roles = {c.get("role") for c in body2["chunks"] if c.get("role")}
    assert "parent" in roles and "child" in roles


def test_chunk_preview_text_and_semantic_degrades(env):
    client, *_ = env
    response = client.post(
        "/api/chunk-preview",
        data={
            "text": "# 质保\n\n整机质保十二个月，电池六个月。\n",
            "fileName": "质保.md",
            "chunkSize": "300",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["chunkCount"] >= 1

    # semantic without LLM: degrade + warning, not hard 422
    soft = client.post(
        "/api/chunk-preview",
        data={"text": "hello world content enough for a chunk preview sample.", "chunkStrategy": "semantic", "fileName": "s.md"},
    )
    assert soft.status_code == 200, soft.text
    body = soft.json()
    assert body["chunkCount"] >= 1
    assert body["options"]["chunkStrategy"] == "semantic" or any("降级" in w or "语义" in w for w in (body.get("warnings") or []))
    # aliases accepted
    alias = client.post(
        "/api/chunk-preview",
        data={"text": "alias semantic sample text for preview path.", "chunkStrategy": "llm_semantic", "fileName": "a.md"},
    )
    assert alias.status_code == 200, alias.text


def test_upload_persists_chunk_keywords(env):
    client, scope, *_ = env
    kb = create_kb(client, name="密灯切块测")
    path = FIXTURE_MIDENG / "F1_账号申诉FAQ.md"
    if not path.exists():
        path = TESTDATA / "01_售后FAQ.md"
    response = client.post(
        f"/api/knowledge-bases/{kb}/documents",
        files=[("files", (path.name, path.read_bytes()))],
        data={"autoPublish": "false", "imageUnderstanding": "false", "chunkSize": "400"},
    )
    assert response.status_code == 202, response.text
    task = response.json()["tasks"][0]
    ingestion.process_task(task["id"])
    with scope() as db:
        doc = get_entity(db, "doc", task["docId"]).payload
        chunks = doc.get("draftChunks") or []
        assert chunks
        assert any((c.get("metadata") or {}).get("keywords") for c in chunks)
