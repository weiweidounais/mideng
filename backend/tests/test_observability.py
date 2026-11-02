"""TraceId generation + observability read APIs project existing entities."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import applications as apps
from app import observability as obs
from app import rag
from app.db import Base, get_entity, list_entities, put_entity
from app.security import Actor, current_session, require_manager


@pytest.fixture
def env(monkeypatch):
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

    monkeypatch.setattr(obs, "db_session", session)
    monkeypatch.setattr(rag, "db_session", session)
    monkeypatch.setattr(apps, "db_session", session)

    actor = {"value": Actor("owner-a", "admin", "csrf")}
    app = FastAPI()
    app.include_router(obs.router, prefix="/api")
    app.include_router(rag.router, prefix="/api")
    app.include_router(apps.router, prefix="/api")
    app.dependency_overrides[current_session] = lambda: actor["value"]
    app.dependency_overrides[require_manager] = lambda: actor["value"]

    with session() as db:
        put_entity(db, "setting", {"id": "system", "chatConcurrency": 10})
        put_entity(db, "kb", {"id": "kb1", "name": "制度库"})

    with TestClient(app) as client:
        yield client, session, actor
    engine.dispose()


def test_base_log_includes_trace_id():
    actor = Actor("u1", "user", "csrf")
    log = rag._base_log("req-abc", actor, "问题", ["库A"], "chat")
    assert log["id"] == "req-abc"
    assert log["traceId"] == "req-abc"
    assert log["source"] == "chat"


def test_list_and_get_chat_trace(env):
    client, session, _ = env
    with session() as db:
        put_entity(
            db,
            "log",
            {
                "id": "req-chat1",
                "traceId": "req-chat1",
                "question": "差旅标准？",
                "answer": "500元",
                "model": "cloud-chat",
                "kbName": "制度库",
                "status": "success",
                "tokens": 120,
                "inputTokens": 80,
                "outputTokens": 40,
                "duration": 1.2,
                "firstToken": 0.4,
                "time": "10/29 18:00",
                "createdAt": "2026-10-29T10:00:00+00:00",
                "role": "使用者",
                "source": "chat",
                "steps": [
                    {"name": "向量检索", "model": "emb", "duration": 0.2, "tokens": None, "status": "成功", "meter": "local"},
                    {"name": "生成回答", "model": "cloud-chat", "duration": 0.9, "tokens": 120, "status": "成功", "meter": "cloud"},
                ],
            },
            owner="owner-a",
        )

    listed = client.get("/api/observability/traces", params={"rootType": "chat"})
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["traceId"] == "req-chat1"
    assert body["items"][0]["tokens"] == 120

    detail = client.get("/api/observability/traces/req-chat1")
    assert detail.status_code == 200
    data = detail.json()
    assert data["trace"]["rootType"] == "chat"
    assert len(data["steps"]) == 2
    assert data["input"] == "差旅标准？"
    assert data["output"] == "500元"
    assert data["buildStages"] == []
    assert data["toolCalls"] == []
    assert data["skillCalls"] == []


def test_import_trace_pipeline_from_task_and_log(env):
    client, session, _ = env
    tid = "task-build-1"
    with session() as db:
        put_entity(
            db,
            "task",
            {
                "id": tid,
                "traceId": tid,
                "kbId": "kb1",
                "docId": "doc1",
                "name": "差旅.pdf",
                "progress": 100,
                "status": "success",
                "stage": "索引完成",
                "autoPublish": True,
                "time": "10/29 17:00",
                "createdAt": "2026-10-29T09:00:00+00:00",
                "operation": "import",
                "options": {"parser": "auto", "chunkSize": 600, "chunkStrategy": "recursive"},
            },
            parent_id="kb1",
        )
        put_entity(
            db,
            "log",
            {
                "id": tid,
                "traceId": tid,
                "question": "导入文档：差旅.pdf",
                "answer": "知识索引构建完成",
                "model": "emb",
                "kbName": "制度库",
                "status": "success",
                "tokens": 40,
                "inputTokens": None,
                "outputTokens": None,
                "duration": 3.5,
                "firstToken": None,
                "time": "10/29 17:01",
                "createdAt": "2026-10-29T09:01:00+00:00",
                "role": "知识库管理人员",
                "source": "import",
                "taskId": tid,
                "documentId": "doc1",
                "steps": [
                    {"name": "文档解析与图像理解", "model": "local", "duration": 1.1, "tokens": None, "status": "成功"},
                    {"name": "元数据抽取", "model": "rules", "duration": 0.2, "tokens": None, "status": "成功"},
                    {"name": "向量索引", "model": "emb", "duration": 2.0, "tokens": 40, "status": "成功"},
                ],
            },
        )

    detail = client.get(f"/api/observability/traces/{tid}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["trace"]["traceId"] == tid
    assert data["trace"]["rootType"] == "import"
    assert data["trace"]["tokens"] == 40
    stages = {s["stage"]: s for s in data["buildStages"]}
    assert stages["upload_received"]["status"] == "success"
    assert stages["parse"]["status"] == "success"
    assert stages["parse"]["duration"] == 1.1
    assert stages["chunk"]["status"] == "success"
    assert stages["chunk"]["duration"] is None  # not separately timed
    assert stages["metadata_extract"]["status"] == "success"
    assert stages["index"]["tokens"] == 40
    assert stages["publish"]["status"] == "success"


def test_application_run_trace_and_gaps(env):
    client, session, _ = env
    run_id = "run-app-1"
    with session() as db:
        put_entity(
            db,
            "application_run",
            {
                "id": run_id,
                "runId": run_id,
                "traceId": run_id,
                "applicationId": "app1",
                "applicationName": "知识问答",
                "revision": 1,
                "mode": "published",
                "input": "报销材料",
                "status": "success",
                "output": "需要发票",
                "sources": [],
                "steps": [
                    {"nodeId": "start", "label": "开始", "kind": "start", "status": "success", "output": "报销材料", "duration": 0.01, "tokens": None, "meter": "local"},
                    {"nodeId": "out", "label": "输出", "kind": "output", "status": "success", "output": "需要发票", "duration": 0.02, "tokens": None, "meter": "local"},
                ],
                "tokens": None,
                "duration": 0.05,
                "createdAt": "2026-10-29T11:00:00+00:00",
            },
            owner="owner-a",
            parent_id="app1",
        )

    listed = client.get("/api/observability/traces", params={"rootType": "application"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    detail = client.get(f"/api/observability/traces/{run_id}")
    data = detail.json()
    assert data["trace"]["rootType"] == "application"
    assert data["input"] == "报销材料"
    assert data["trace"]["tokens"] is None
    assert data["toolCalls"] == []
    assert data["skillCalls"] == []
    assert data["harnessErrors"] == []
    assert any("工具" in g or "tool" in g.lower() for g in data["gaps"])


def test_overview_and_billing_no_fake_money(env):
    client, session, _ = env
    with session() as db:
        put_entity(
            db,
            "log",
            {
                "id": "req-b1",
                "traceId": "req-b1",
                "question": "q",
                "answer": "a",
                "model": "m",
                "kbName": "k",
                "status": "success",
                "tokens": 10,
                "inputTokens": None,
                "outputTokens": None,
                "duration": 1,
                "firstToken": None,
                "time": "t",
                "createdAt": "2026-10-29T12:00:00+00:00",
                "role": "admin",
                "source": "retrieval",
                "steps": [],
            },
        )
        put_entity(
            db,
            "log",
            {
                "id": "req-b2",
                "traceId": "req-b2",
                "question": "q2",
                "answer": "a2",
                "model": "m",
                "kbName": "k",
                "status": "failed",
                "tokens": None,
                "inputTokens": None,
                "outputTokens": None,
                "duration": 1,
                "firstToken": None,
                "time": "t",
                "createdAt": "2026-10-29T12:01:00+00:00",
                "role": "admin",
                "source": "retrieval",
                "steps": [],
            },
        )

    ov = client.get("/api/observability/overview").json()
    assert ov["requests"] >= 2
    assert ov["failed"] >= 1
    assert ov["tokensKnown"] >= 10
    assert ov["tokensUnknownCount"] >= 1

    bill = client.get("/api/observability/billing").json()
    assert bill["pricingConfigured"] is False
    assert "单价" in bill["notice"] or "token" in bill["notice"].lower()
    row = next(i for i in bill["items"] if i["source"] == "retrieval")
    assert row["tokensKnown"] == 10
    assert row["tokensUnknownCount"] == 1
    assert "est" not in row and "amount" not in row


def test_missing_trace_404(env):
    client, _, _ = env
    assert client.get("/api/observability/traces/does-not-exist").status_code == 404


def test_new_task_sets_trace_id(env):
    _, session, _ = env
    from app import ingestion

    monkey_session = session
    # patch ingestion db if needed — call _new_task with our session via put
    with monkey_session() as db:
        # Directly exercise helper by importing after patch
        import app.ingestion as ing

        # Use same engine session by patching
        task = {
            "id": "manual",
        }
    # Unit-level: construct like helper
    with session() as db:
        doc = {"id": "d1", "kbId": "kb1", "name": "f.md"}
        # Patch ingestion.db_session isn't required for _new_task which takes db
        from app.ingestion import _new_task

        # Need put_entity on same session — monkeypatch ingestion's put is from db module, fine
        t = _new_task(db, doc, {"autoPublish": True}, "import")
        assert t["id"] == t["traceId"]
        assert get_entity(db, "task", t["id"]).payload["traceId"] == t["id"]


def test_application_run_persists_trace_id(env, monkeypatch):
    client, session, _ = env

    def simple():
        return {
            "name": "模板",
            "description": "",
            "nodes": [
                {"id": "start", "kind": "start", "label": "开始", "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "text", "kind": "template", "label": "模板", "position": {"x": 0, "y": 0}, "config": {"template": "收到：{{input}}"}},
                {"id": "out", "kind": "output", "label": "输出", "position": {"x": 0, "y": 0}, "config": {"template": "{{previous.output}}"}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "text"},
                {"id": "e2", "source": "text", "target": "out"},
            ],
        }

    created = client.post("/api/applications", json=simple())
    assert created.status_code in (200, 201)
    app_id = created.json()["id"]
    pub = client.post(f"/api/applications/{app_id}/publish")
    assert pub.status_code == 200
    result = client.post(f"/api/applications/{app_id}/run", json={"input": "hello", "mode": "published"})
    assert result.status_code == 200
    body = result.json()
    assert body["traceId"] == body["id"] == body["runId"]
    with session() as db:
        stored = get_entity(db, "application_run", body["id"]).payload
        assert stored["traceId"] == body["id"]


def test_trace_to_case_good_and_list(env):
    client, session, *_ = env
    with session() as db:
        put_entity(db, "log", {
            "id": "req-case-1", "traceId": "req-case-1", "source": "chat",
            "question": "质保多久？", "answer": "十二个月", "status": "success",
            "tokens": None, "duration": 0.1, "time": "2026-10-30 12:00",
            "createdAt": "2026-10-30T04:00:00+00:00", "owner": "owner-a",
            "sources": [{"docId": "doc-1", "title": "质保"}],
        })
    good = client.post("/api/observability/traces/req-case-1/to-case", json={"label": "good"})
    assert good.status_code == 200, good.text
    body = good.json()
    assert body["ok"] is True
    assert body["case"]["label"] == "good"
    assert body["case"]["query"] == "质保多久？"
    assert "doc-1" in body["case"]["expectedDocIds"]
    assert body["case"]["importable"]["query"] == "质保多久？"

    listed = client.get("/api/observability/eval-cases?label=good")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(c["id"] == body["case"]["id"] for c in items)


def test_trace_to_case_missing_soft_fail(env):
    client, *_ = env
    missing = client.post("/api/observability/traces/does-not-exist/to-case", json={"label": "bad"})
    assert missing.status_code == 200, missing.text
    assert missing.json()["ok"] is False
    assert missing.json()["case"] is None


def test_trace_to_case_from_application_run(env):
    client, session, *_ = env
    with session() as db:
        put_entity(db, "application_run", {
            "id": "run-case-1", "runId": "run-case-1", "traceId": "run-case-1",
            "applicationId": "app-1", "applicationName": "问答", "input": "如何退款",
            "output": "提交工单", "status": "success", "tokens": None, "duration": 0.2,
            "createdAt": "2026-10-30T04:00:00+00:00", "sources": [],
        }, owner="owner-a", parent_id="app-1")
    res = client.post("/api/observability/traces/run-case-1/to-case", json={"label": "bad", "note": "答非所问"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["case"]["label"] == "bad"
    assert body["case"]["query"] == "如何退款"
    assert body["case"]["rootType"] == "application"
